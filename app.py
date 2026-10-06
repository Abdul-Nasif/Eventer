import os
import re
import uuid
import secrets
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort, jsonify
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload cap

SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET        = "payment-screenshots"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
UPI_ID        = os.getenv("UPI_ID", "yourupi@bank")
UPI_NAME      = os.getenv("UPI_NAME", "Your Business")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------------------------------------------------------
# Plans (drive the 3 pricing cards + form generation)
# ------------------------------------------------------------------
PLANS = {
    "individual": {
        "label": "Individual",
        "price": 299,
        "count": 1,
        "cta": "Register now",
        "theme": "card-indigo",
        "bg": "bg1",
        "description": "For a single attendee who wants full access to the event.",
    },
    "couple": {
        "label": "Couple",
        "price": 499,
        "count": 2,
        "cta": "Register now",
        "theme": "card-purple",
        "bg": "bg2",
        "description": "Bring a partner — two attendees, one great price.",
    },
    "offer_4_1": {
        "label": "4+1 Offer",
        "price": 1199,
        "count": 5,
        "cta": "Register now",
        "theme": "card-pink",
        "bg": "bg3",
        "description": "Group of five — four paid, one free. Perfect for teams.",
    },
}

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def generate_group_code() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    for _ in range(10):
        code = "RG-" + "".join(secrets.choice(alphabet) for _ in range(6))
        existing = sb.table("registrations").select("id").eq("group_code", code).limit(1).execute()
        if not existing.data:
            return code
    raise RuntimeError("Could not generate a unique group code.")

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return wrapper

# ==================================================================
# PUBLIC ROUTES
# ==================================================================
@app.route("/")
def index():
    return render_template("index.html", plans=PLANS)


# -------------------------- REGISTER ------------------------------
@app.route("/register/<plan_type>")
def register(plan_type):
    plan = PLANS.get(plan_type)
    if not plan:
        abort(404)
    return render_template("register.html", plan_type=plan_type, plan=plan)


@app.route("/register/<plan_type>", methods=["POST"])
def register_post(plan_type):
    plan = PLANS.get(plan_type)
    if not plan:
        abort(404)

    participants = []
    for i in range(plan["count"]):
        name       = (request.form.get(f"p_name_{i}") or "").strip()
        phone      = (request.form.get(f"p_phone_{i}") or "").strip()
        email      = (request.form.get(f"p_email_{i}") or "").strip()
        address    = (request.form.get(f"p_address_{i}") or "").strip()
        profession = (request.form.get(f"p_profession_{i}") or "").strip()

        if not (name and phone and email and address and profession):
            flash(f"Please complete all fields for participant {i+1}.", "error")
            return redirect(url_for("register", plan_type=plan_type))

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash(f"Invalid email for participant {i+1}.", "error")
            return redirect(url_for("register", plan_type=plan_type))

        if profession not in ("student", "other"):
            profession = "other"

        participants.append({
            "name": name,
            "phone": phone,
            "email": email,
            "address": address,
            "profession": profession,
        })

    group_code = generate_group_code()

    reg_res = sb.table("registrations").insert({
        "group_code": group_code,
        "plan_type": plan_type,
        "amount": plan["price"],
        "status": "pending_payment",
    }).execute()

    if not reg_res.data:
        flash("Database error while creating registration. Please try again.", "error")
        return redirect(url_for("register", plan_type=plan_type))

    reg_id = reg_res.data[0]["id"]

    sb.table("participants").insert(
        [{"registration_id": reg_id, **p} for p in participants]
    ).execute()

    return redirect(url_for("payment", group_code=group_code))


# --------------------------- PAYMENT ------------------------------
@app.route("/payment/<group_code>")
def payment(group_code):
    r = sb.table("registrations").select("*").eq("group_code", group_code).limit(1).execute()
    if not r.data:
        abort(404)

    reg = r.data[0]
    if reg["status"] != "pending_payment":
        return redirect(url_for("success", group_code=group_code))

    plan = PLANS.get(reg["plan_type"], {})
    return render_template(
        "payment.html",
        reg=reg, plan=plan, upi_id=UPI_ID, upi_name=UPI_NAME,
    )


@app.route("/payment/<group_code>", methods=["POST"])
def payment_post(group_code):
    r = sb.table("registrations").select("*").eq("group_code", group_code).limit(1).execute()
    if not r.data:
        abort(404)
    reg = r.data[0]

    utr  = (request.form.get("utr") or "").strip()
    file = request.files.get("screenshot")

    if not utr or not file or not file.filename:
        flash("UTR and payment screenshot are both required.", "error")
        return redirect(url_for("payment", group_code=group_code))

    if not re.fullmatch(r"[A-Za-z0-9]{6,30}", utr):
        flash("UTR must be 6–30 alphanumeric characters.", "error")
        return redirect(url_for("payment", group_code=group_code))

    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    if ext not in ("png", "jpg", "jpeg", "webp"):
        flash("Only PNG / JPG / WEBP screenshots are accepted.", "error")
        return redirect(url_for("payment", group_code=group_code))

    path = f"{reg['id']}/{uuid.uuid4().hex}.{ext}"

    try:
        sb.storage.from_(BUCKET).upload(
            path,
            file.read(),
            {"content-type": file.mimetype or f"image/{ext}", "upsert": "true"},
        )
    except Exception as e:
        flash(f"Screenshot upload failed: {e}", "error")
        return redirect(url_for("payment", group_code=group_code))

    sb.table("registrations").update({
        "utr": utr,
        "screenshot_path": path,
        "status": "pending_approval",
    }).eq("id", reg["id"]).execute()

    return redirect(url_for("success", group_code=group_code))


# --------------------------- SUCCESS ------------------------------
@app.route("/success/<group_code>")
def success(group_code):
    r = sb.table("registrations").select("*").eq("group_code", group_code).limit(1).execute()
    if not r.data:
        abort(404)
    return render_template("success.html", reg=r.data[0])


# ==================================================================
# ADMIN
# ==================================================================
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Invalid admin password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin():
    res = (
        sb.table("registrations")
          .select("*, participants(*)")
          .order("created_at", desc=True)
          .execute()
    )
    return render_template("admin.html", registrations=res.data or [], plans=PLANS)


@app.route("/admin/screenshot/<reg_id>")
@login_required
def admin_screenshot(reg_id):
    r = (sb.table("registrations")
           .select("screenshot_path")
           .eq("id", reg_id)
           .limit(1)
           .execute())

    if not r.data or not r.data[0].get("screenshot_path"):
        abort(404)

    path = r.data[0]["screenshot_path"]

    try:
        signed = sb.storage.from_(BUCKET).create_signed_url(path, 3600)
    except Exception as e:
        app.logger.exception("signed-url error")
        abort(500, f"signed-url error: {e}")

    # supabase-py 1.x → {"signedURL": "..."}
    # supabase-py 2.x → {"signedURL": "..."} or {"signed_url": "..."}
    url = None
    if isinstance(signed, dict):
        url = (signed.get("signedURL")
               or signed.get("signed_url")
               or signed.get("signedUrl"))
        # some versions nest it: {"data": {"signedURL": "..."}}
        if not url and isinstance(signed.get("data"), dict):
            url = (signed["data"].get("signedURL")
                   or signed["data"].get("signed_url"))
    elif isinstance(signed, str):
        url = signed

    if not url:
        app.logger.error("unexpected signed-url payload: %r", signed)
        abort(500, "Could not create signed URL")

    return redirect(url)


@app.route("/admin/approve/<reg_id>", methods=["POST"])
@login_required
def admin_approve(reg_id):
    sb.table("registrations").update({"status": "approved"}).eq("id", reg_id).execute()
    return jsonify({"ok": True, "status": "approved"})


@app.route("/admin/reject/<reg_id>", methods=["POST"])
@login_required
def admin_reject(reg_id):
    notes = (request.get_json(silent=True) or {}).get("notes", "")
    sb.table("registrations").update(
        {"status": "rejected", "notes": notes}
    ).eq("id", reg_id).execute()
    return jsonify({"ok": True, "status": "rejected"})


# ==================================================================
# Entrypoint
# ==================================================================
if __name__ == "__main__":
    app.run(debug=True, port=5000)