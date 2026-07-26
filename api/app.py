import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)  # one level up from api/, where .env lives

# Load .env explicitly by path so it works no matter which folder you
# run "python app.py" from (this fixes DNS/getaddrinfo errors that
# happen when SUPABASE_URL silently comes back empty or stale).
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, '.env'))

app = Flask(
    __name__, 
    template_folder=os.path.join(BASE_DIR, 'templates'), 
    static_folder=os.path.join(BASE_DIR, 'static'), 
    static_url_path='/static'
)

# Robust Session Security Config
app.secret_key = os.environ.get("SECRET_KEY", "vaagdevi_mun_super_secret_key_2026")
app.config['SESSION_COOKIE_NAME'] = 'vmun_admin_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Always re-check template files on disk, even with debug=False, so
# editing templates.html doesn't require a full server restart to show up.
app.config['TEMPLATES_AUTO_RELOAD'] = True

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "affan")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "orion")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

PLACEHOLDER_MARKERS = ("YOUR-PROJECT-REF", "YOUR-SUPABASE-SERVICE-ROLE-KEY")

if SUPABASE_URL and SUPABASE_KEY and not any(m in (SUPABASE_URL + SUPABASE_KEY) for m in PLACEHOLDER_MARKERS):
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("Warning: Supabase credentials missing or still set to placeholder values in .env.")
    print(f"  .env expected at: {os.path.join(PROJECT_ROOT, '.env')}")
    print(f"  SUPABASE_URL currently resolves to: {SUPABASE_URL!r}")
    supabase = None

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Debug helper to verify env credentials on server spin up
print(f"--- SERVER CONFIGURATION BOOT ---")
print(f"Target Admin Username: {ADMIN_USERNAME}")
print(f"Supabase Endpoint: {SUPABASE_URL}")
print(f"---------------------------------")

# -------------------------------------------------------------
# TEMPLATE ROUTING
# -------------------------------------------------------------
PUBLIC_DOMAIN = os.environ.get("PUBLIC_DOMAIN", "")

@app.route('/')
def home():
    return render_template('index.html', public_domain=PUBLIC_DOMAIN)

@app.route('/admin-login')
def admin_login_page():
    if session.get('is_admin') is True:
        return redirect(url_for('admin_dashboard_page'))
    return render_template('admin_login.html')

@app.route('/admin-dashboard')
def admin_dashboard_page():
    if session.get('is_admin') is not True:
        return redirect(url_for('admin_login_page'))
    return render_template('admin.html')

# -------------------------------------------------------------
# PUBLIC E-TICKET QR VERIFICATION SCREEN (NO LOGIN REQUIRED)
# -------------------------------------------------------------
# @app.route('/verify-ticket/<reg_id>', methods=['GET'])
# def verify_ticket(reg_id):
#     try:
#         # Fetch status in real-time from Supabase
#         result = supabase.table('registrations').select('*').eq('registration_id', reg_id).execute()
#         if len(result.data) == 0:
#             return render_template('verify_ticket.html', found=False, reg_id=reg_id)
        
#         participant = result.data[0]
#         return render_template('verify_ticket.html', found=True, p=participant)
#     except Exception as e:
#         print("Verification query error:", str(e))
#         return "Internal Database Error", 500

# -------------------------------------------------------------
# REST API ENDPOINTS
# -------------------------------------------------------------
@app.route('/api/register', methods=['POST'])
def register():
    if supabase is None:
        return jsonify({'error': 'Server is not configured: Supabase credentials are missing or invalid in .env. Check the server logs.'}), 500
    try:
        if 'screenshot' not in request.files:
            return jsonify({'error': 'Payment screenshot is required.'}), 400
        
        file = request.files['screenshot']
        if file.filename == '':
            return jsonify({'error': 'No file selected.'}), 400

        if not (file and allowed_file(file.filename)):
            return jsonify({'error': 'Invalid file format. Only JPEG, JPG, and PNG are accepted.'}), 400

        form_data_str = request.form.get('data')
        if not form_data_str:
            return jsonify({'error': 'Form data package missing.'}), 400
        
        form_data = json.loads(form_data_str)

        # 1. Check if UTR already exists in database
        check_utr = supabase.table('registrations').select('id').eq('utr_id', form_data['utrId']).execute()
        if len(check_utr.data) > 0:
            return jsonify({'error': 'This UTR ID has already been registered.'}), 400

        # 2. Upload file to Supabase Storage Bucket
        filename = secure_filename(file.filename)
        unique_filename = f"{os.urandom(8).hex()}-{filename}"
        
        file_bytes = file.read()
        supabase.storage.from_('receipts').upload(
            path=unique_filename,
            file=file_bytes,
            file_options={"content-type": file.content_type}
        )
        
        screenshot_url = supabase.storage.from_('receipts').get_public_url(unique_filename)

        # 3. Create Unique Registration ID
        count_res = supabase.table('registrations').select('id', count='exact').execute()
        next_num = str(count_res.count + 101).zfill(6)
        registration_id = f"VMUN-2026-{next_num}"

        # 4. Insert Metadata Into Supabase Database
        # pref1 / pref2 each look like:
        #   { committee: 'UNGA' | 'TLA',
        #     sub1: { continent, countries: [c1,c2,c3] } or { zone, mla },
        #     sub2: { same shape as sub1 } }
        # sub1 / sub2 are stored as-is in jsonb columns.
        insert_payload = {
            "registration_id": registration_id,
            "full_name": form_data['fullName'],
            "age": int(form_data['age']),
            "institution": form_data['institution'],
            "year_of_study": form_data['yearOfStudy'],
            "email": form_data['email'],
            "alt_email": form_data.get('altEmail') or None,
            "contact": form_data['contact'],
            "alt_contact": form_data.get('altContact') or None,
            "has_experience": form_data['hasExperience'],
            "pref1_committee": form_data['pref1']['committee'],
            "pref1_sub1": form_data['pref1'].get('sub1', {}),
            "pref1_sub2": form_data['pref1'].get('sub2', {}),
            "pref2_committee": form_data['pref2']['committee'],
            "pref2_sub1": form_data['pref2'].get('sub1', {}),
            "pref2_sub2": form_data['pref2'].get('sub2', {}),
            "utr_id": form_data['utrId'],
            "screenshot_path": screenshot_url
        }

        supabase.table('registrations').insert(insert_payload).execute()
        return jsonify({'success': True, 'registrationId': registration_id}), 201

    except Exception as e:
        print("Registration Error Details:", str(e))
        return jsonify({'error': f"Failed to register: {str(e)}"}), 500

@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    data = request.json or {}
    username_input = data.get('username')
    password_input = data.get('password')
    
    if username_input == ADMIN_USERNAME and password_input == ADMIN_PASSWORD:
        session.clear()
        session['is_admin'] = True
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid username or password credentials'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def api_admin_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/admin/registrations', methods=['GET'])
def get_admin_registrations():
    if session.get('is_admin') is not True:
        return jsonify({'error': 'Unauthorized access keys.'}), 401
    try:
        result = supabase.table('registrations').select('*').order('created_at', desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/approve/<reg_id>', methods=['PUT'])
def approve_user(reg_id):
    if session.get('is_admin') is not True:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        res = supabase.table('registrations').update({"status": "Approved"}).eq("registration_id", reg_id).execute()
        return jsonify({'success': True, 'data': res.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/save-allocation/<reg_id>', methods=['PUT'])
def save_allocation(reg_id):
    if session.get('is_admin') is not True:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.json
        res = supabase.table('registrations').update({
            "allocated_country": data.get('allocated_country', ''),
            "allocated_mla": data.get('allocated_mla', '')
        }).eq("registration_id", reg_id).execute()
        return jsonify({'success': True, 'data': res.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 3000)), debug=False)