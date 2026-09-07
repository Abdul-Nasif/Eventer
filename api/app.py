import os
import json
import io
import base64
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Try-except block to gracefully handle missing third-party packages
try:
    import cv2
    import numpy as np
    import qrcode
except ImportError as e:
    print(f"\n[ERROR] Missing dependencies: {e}")
    print("[ERROR] Please execute: pip install opencv-python-headless numpy qrcode pillow\n")

# Load environment variables
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__, 
    template_folder=os.path.join(BASE_DIR, 'templates'), 
    static_folder=os.path.join(BASE_DIR, 'static'), 
    static_url_path='/static'
)

# Session Security Configuration
app.secret_key = os.environ.get("SECRET_KEY", "vaagdevi_mun_super_secret_key_2026")
app.config['SESSION_COOKIE_NAME'] = 'vmun_admin_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "affan")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "orion")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("Warning: Supabase credentials missing from .env configurations.")
    supabase = None

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------------------------------------------------
# HELPERS FOR QR DECODING & GENERATION
# -------------------------------------------------------------
def decode_qr_from_file(file_storage):
    """Reads file bytes directly, decodes the QR code with OpenCV, and returns payload."""
    try:
        file_bytes = np.frombuffer(file_storage.read(), np.uint8)
        file_storage.seek(0) # Always reset stream pointer immediately
        
        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if img is None:
            print("[DEBUG] OpenCV could not parse the image stream.")
            return None
            
        detector = cv2.QRCodeDetector()
        data, bbox, straight_qrcode = detector.detectAndDecode(img)
        
        if data:
            print(f"[DEBUG] QR code decoded payload: {data}")
            return data.strip()
        print("[DEBUG] No QR code detected in the image.")
        return None
    except Exception as e:
        print("[ERROR] Exception occurred in decode_qr_from_file:", str(e))
        return None

def generate_qr_base64(data):
    """Generates a QR code base64 string for embedding in templates."""
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print("[ERROR] Failed to generate QR Base64:", str(e))
        return ""

# -------------------------------------------------------------
# TEMPLATE ROUTING
# -------------------------------------------------------------
@app.route('/')
def home():
    public_domain = os.environ.get("PUBLIC_DOMAIN", "http://127.0.0.1:3000")
    coupon_code = os.environ.get("COUPON_CODE", "VAAG450")
    return render_template('index.html', public_domain=public_domain, coupon_code=coupon_code)

@app.route('/admin-login')
def admin_login_page():
    if session.get('is_admin') is True:
        return redirect(url_for('admin_dashboard_page'))
    return render_template('admin_login.html')

@app.route('/admin-dashboard')
def admin_dashboard_page():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login_page'))
    return render_template('admin.html')

@app.route('/verify-ticket/<reg_id>', methods=['GET'])
def verify_ticket(reg_id):
    try:
        result = supabase.table('registrations').select('*').eq('registration_id', reg_id).execute()
        if len(result.data) == 0:
            return render_template('verify_ticket.html', found=False, reg_id=reg_id)
        
        p = result.data[0]
        return render_template('verify_ticket.html', found=True, p=p)
    except Exception as e:
        print("Verification query error:", str(e))
        return "Internal Database Error", 500

# -------------------------------------------------------------
# EVENTER 2.0: E-PASS & ATTENDANCE UPLOAD ROUTES
# -------------------------------------------------------------
@app.route('/e-pass/<reg_id>', methods=['GET'])
def view_epass(reg_id):
    """Renders the unique digital pass with custom QR code."""
    try:
        result = supabase.table('registrations').select('*').eq('registration_id', reg_id).execute()
        if len(result.data) == 0:
            return "Registration context not found.", 404
        
        p = result.data[0]
        qr_image = generate_qr_base64(p['registration_id'])
        return render_template('epass.html', p=p, qr_code=qr_image)
    except Exception as e:
        print("E-Pass rendering error:", str(e))
        return "Internal Server Error", 500

@app.route('/upload-pass', methods=['POST'])
def upload_pass():
    """Processes uploaded e-pass image, parses QR code, updates attendance and department in database."""
    if 'epass_file' not in request.files:
        flash("No file was found in the submission payload.", "error")
        return redirect(url_for('home'))
        
    file = request.files['epass_file']
    department = request.form.get('department', '').strip()
    
    if not department:
        flash("Department entry is required for checking in.", "error")
        return redirect(url_for('home'))
        
    if file.filename == '':
        flash("Please choose an e-pass file to upload first.", "error")
        return redirect(url_for('home'))
        
    if file and allowed_file(file.filename):
        # Extract the QR data using OpenCV helper
        scanned_data = decode_qr_from_file(file)
        
        if not scanned_data:
            flash("Could not read a valid QR code. Ensure the uploaded e-pass photo is sharp and the code is fully visible.", "error")
            return redirect(url_for('home'))
            
        # Extract clean registration_id if the QR contains a full URL
        scanned_id = scanned_data.strip().rstrip('/')
        if '/' in scanned_id:
            scanned_id = scanned_id.split('/')[-1]
            
        try:
            # Query record from Supabase table using the parsed, clean ID
            result = supabase.table('registrations').select('*').eq('registration_id', scanned_id).execute()
            if len(result.data) == 0:
                flash(f"Invalid e-pass. Ticket ID '{scanned_id}' was not found in our registration records.", "error")
                return redirect(url_for('home'))
                
            p = result.data[0]
            
            # Warn if check-in is already complete
            if p.get('attended') is True:
                flash(f"Check-in duplicate. Attendance has already been logged for {p['full_name']}.", "warning")
                return redirect(url_for('home'))
                
            # Perform update including newly supplied department
            now_iso = datetime.utcnow().isoformat()
            supabase.table('registrations').update({
                "attended": True,
                "attendance_time": now_iso,
                "department": department
            }).eq("registration_id", scanned_id).execute()
            
            flash(f"Success! Welcome, {p['full_name']} ({department}). Attendance verified.", "success")
            return redirect(url_for('home'))
            
        except Exception as e:
            print("[ERROR] Supabase database transaction failed:", str(e))
            flash("Database validation error occurred. Make sure table columns match.", "error")
            return redirect(url_for('home'))
    else:
        flash("Unsupported file extension. Only PNG, JPG, and JPEG images are allowed.", "error")
        return redirect(url_for('home'))

# -------------------------------------------------------------
# REST API ENDPOINTS
# -------------------------------------------------------------
@app.route('/api/register', methods=['POST'])
def register():
    try:
        screenshot_file = request.files.get('screenshot') or request.files.get('receipt')
        if not screenshot_file:
            return jsonify({'error': 'Payment screenshot is required.'}), 400

        form_data_str = request.form.get('data')
        if not form_data_str:
            return jsonify({'error': 'Metadata packet missing.'}), 400
        
        form_data = json.loads(form_data_str)
        reg_type = form_data.get('regType', 'individual')

        check_utr = supabase.table('registrations').select('id').eq('utr_id', form_data['utrId']).execute()
        if len(check_utr.data) > 0:
            return jsonify({'error': 'This UTR ID has already been registered.'}), 400

        screenshot_name = secure_filename(screenshot_file.filename)
        screenshot_unique_name = f"receipt-{os.urandom(8).hex()}-{screenshot_name}"
        supabase.storage.from_('receipts').upload(screenshot_unique_name, screenshot_file.read(), {"content-type": screenshot_file.content_type})
        screenshot_url = supabase.storage.from_('receipts').get_public_url(screenshot_unique_name)

        max_res = supabase.table('registrations').select('id').order('id', desc=True).limit(1).execute()
        highest_id = max_res.data[0]['id'] if max_res.data else 0

        registered_ids = []

        if reg_type == 'individual':
            photo_file = request.files.get('photo')
            if not photo_file:
                return jsonify({'error': 'Profile photo is required.'}), 400

            photo_name = secure_filename(photo_file.filename)
            photo_unique_name = f"photo-{os.urandom(8).hex()}-{photo_name}"
            supabase.storage.from_('receipts').upload(photo_unique_name, photo_file.read(), {"content-type": photo_file.content_type})
            photo_url = supabase.storage.from_('receipts').get_public_url(photo_unique_name)

            registration_id = f"VMUN-2026-{str(highest_id + 101).zfill(6)}"

            pref1_committee = 'UNGA'
            if 'pref1_committee' in form_data:
                pref1_committee = form_data['pref1_committee']
            elif 'pref1' in form_data and isinstance(form_data['pref1'], dict):
                pref1_committee = form_data['pref1'].get('committee', 'UNGA')

            pref2_committee = 'TLA' if pref1_committee == 'UNGA' else 'UNGA'

            insert_payload = {
                "registration_id": registration_id,
                "full_name": form_data['fullName'],
                "age": int(form_data['age']),
                "institution": form_data['institution'],
                "year_of_study": form_data['yearOfStudy'],
                "email": form_data['email'],
                "contact": form_data['contact'],
                "has_experience": form_data['hasExperience'],
                
                "unga1_continent": form_data['unga1']['continent'],
                "unga1_countries": form_data['unga1']['selectedCountries'],
                "unga2_continent": form_data['unga2']['continent'],
                "unga2_countries": form_data['unga2']['selectedCountries'],
                "tla1_zone": form_data['tla1']['zone'],
                "tla1_mla": form_data['tla1']['mla'],
                "tla2_zone": form_data['tla2']['zone'],
                "tla2_mla": form_data['tla2']['mla'],
                
                "pref1_committee": pref1_committee,
                "pref1_details": json.dumps(form_data['unga1'] if pref1_committee == 'UNGA' else form_data['tla1']),
                "pref2_committee": pref2_committee,
                "pref2_details": json.dumps(form_data['tla1'] if pref1_committee == 'UNGA' else form_data['unga1']),
                
                "utr_id": form_data['utrId'],
                "screenshot_path": screenshot_url,
                "photo_path": photo_url,
                "group_id": None,
                "attended": False
            }
            supabase.table('registrations').insert(insert_payload).execute()
            registered_ids.append(registration_id)

        else:
            group_id = f"GRP-{os.urandom(4).hex().upper()}"

            for i in range(5):
                photo_file = request.files.get(f'photo_{i}')
                if not photo_file:
                    return jsonify({'error': f'Profile photo for Member {i+1} is missing.'}), 400

                member = form_data['members'][i]
                
                photo_name = secure_filename(photo_file.filename)
                photo_unique_name = f"photo-{os.urandom(8).hex()}-{photo_name}"
                supabase.storage.from_('receipts').upload(photo_unique_name, photo_file.read(), {"content-type": photo_file.content_type})
                photo_url = supabase.storage.from_('receipts').get_public_url(photo_unique_name)

                registration_id = f"VMUN-2026-{str(highest_id + 101 + i).zfill(6)}"

                pref1_committee = 'UNGA'
                if 'pref1_committee' in member:
                    pref1_committee = member['pref1_committee']
                elif 'pref1' in member and isinstance(member['pref1'], dict):
                    pref1_committee = member['pref1'].get('committee', 'UNGA')

                pref2_committee = 'TLA' if pref1_committee == 'UNGA' else 'UNGA'

                insert_payload = {
                    "registration_id": registration_id,
                    "full_name": member['fullName'],
                    "age": int(member['age']),
                    "institution": member['institution'],
                    "year_of_study": member['yearOfStudy'],
                    "email": member['email'],
                    "contact": member['contact'],
                    "has_experience": member['hasExperience'],
                    
                    "unga1_continent": member['unga1']['continent'],
                    "unga1_countries": member['unga1']['selectedCountries'],
                    "unga2_continent": member['unga2']['continent'],
                    "unga2_countries": member['unga2']['selectedCountries'],
                    "tla1_zone": member['tla1']['zone'],
                    "tla1_mla": member['tla1']['mla'],
                    "tla2_zone": member['tla2']['zone'],
                    "tla2_mla": member['tla2']['mla'],
                    
                    "pref1_committee": pref1_committee,
                    "pref1_details": json.dumps(member['unga1'] if pref1_committee == 'UNGA' else member['tla1']),
                    "pref2_committee": pref2_committee,
                    "pref2_details": json.dumps(member['tla1'] if pref1_committee == 'UNGA' else member['unga1']),
                    
                    "utr_id": form_data['utrId'],
                    "screenshot_path": screenshot_url,
                    "photo_path": photo_url,
                    "group_id": group_id,
                    "attended": False
                }
                supabase.table('registrations').insert(insert_payload).execute()
                registered_ids.append(registration_id)

        return jsonify({'success': True, 'registrationId': ", ".join(registered_ids)}), 201

    except Exception as e:
        print("Registration Error:", str(e))
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
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def api_admin_logout():
    session.clear()
    return jsonify({'success': True})

# -------------------------------------------------------------
# REST API FILTERING (Institution / Year / Attendance)
# -------------------------------------------------------------
@app.route('/api/admin/registrations', methods=['GET'])
def get_admin_registrations():
    """Fetches registrations with support for administrative sorting/filtering."""
    if session.get('is_admin') is not True:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        # Start base Supabase query
        query = supabase.table('registrations').select('*')
        
        # Read incoming request parameters
        inst_filter = request.args.get('institution')
        year_filter = request.args.get('year')
        attendance_filter = request.args.get('attended') # True, False, or Empty
        
        if inst_filter:
            query = query.eq('institution', inst_filter)
        if year_filter:
            query = query.eq('year_of_study', year_filter)
        if attendance_filter:
            is_att = attendance_filter.lower() == 'true'
            query = query.eq('attended', is_att)
            
        result = query.order('created_at', desc=True).execute()
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
