import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

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
# TEMPLATE ROUTING
# -------------------------------------------------------------
@app.route('/')
def home():
    public_domain = os.environ.get("PUBLIC_DOMAIN", "http://127.0.0.1:3000")
    return render_template('index.html', public_domain=public_domain)

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
# REST API ENDPOINTS
# -------------------------------------------------------------
@app.route('/api/register', methods=['POST'])
def register():
    try:
        if 'screenshot' not in request.files or 'photo' not in request.files:
            return jsonify({'error': 'Both payment screenshot and participant photo are required.'}), 400
        
        screenshot_file = request.files['screenshot']
        photo_file = request.files['photo']

        if screenshot_file.filename == '' or photo_file.filename == '':
            return jsonify({'error': 'Files cannot be empty.'}), 400

        if not (allowed_file(screenshot_file.filename) and allowed_file(photo_file.filename)):
            return jsonify({'error': 'Invalid format. Only JPEG, JPG, and PNG images are allowed.'}), 400

        form_data_str = request.form.get('data')
        if not form_data_str:
            return jsonify({'error': 'Metadata packet missing.'}), 400
        
        form_data = json.loads(form_data_str)

        # 1. Check if UTR already exists
        check_utr = supabase.table('registrations').select('id').eq('utr_id', form_data['utrId']).execute()
        if len(check_utr.data) > 0:
            return jsonify({'error': 'This UTR ID has already been registered.'}), 400

        # 2. Upload Files
        screenshot_name = secure_filename(screenshot_file.filename)
        screenshot_unique_name = f"receipt-{os.urandom(8).hex()}-{screenshot_name}"
        supabase.storage.from_('receipts').upload(screenshot_unique_name, screenshot_file.read(), {"content-type": screenshot_file.content_type})
        screenshot_url = supabase.storage.from_('receipts').get_public_url(screenshot_unique_name)

        photo_name = secure_filename(photo_file.filename)
        photo_unique_name = f"photo-{os.urandom(8).hex()}-{photo_name}"
        supabase.storage.from_('receipts').upload(photo_unique_name, photo_file.read(), {"content-type": photo_file.content_type})
        photo_url = supabase.storage.from_('receipts').get_public_url(photo_unique_name)

        # 3. Create Unique Registration ID
        count_res = supabase.table('registrations').select('id', count='exact').execute()
        next_num = str(count_res.count + 101).zfill(6)
        registration_id = f"VMUN-2026-{next_num}"

        # 4. Insert payload with 4 dedicated preference values (using Supabase default created_at)
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
            
            # UNGA 1 & 2 details
            "unga1_continent": form_data['unga1']['continent'],
            "unga1_countries": form_data['unga1']['selectedCountries'],
            "unga2_continent": form_data['unga2']['continent'],
            "unga2_countries": form_data['unga2']['selectedCountries'],
            
            # TLA 1 & 2 details
            "tla1_zone": form_data['tla1']['zone'],
            "tla1_mla": form_data['tla1']['mla'],
            "tla2_zone": form_data['tla2']['zone'],
            "tla2_mla": form_data['tla2']['mla'],
            
            # Keep fallback fields filled for backwards compatibility
            "pref1_committee": "UNGA",
            "pref1_continent": form_data['unga1']['continent'],
            "pref1_countries": form_data['unga1']['selectedCountries'],
            "pref2_committee": "TLA",
            "pref2_zone": form_data['tla1']['zone'],
            "pref2_mla": form_data['tla1']['mla'],
            
            "utr_id": form_data['utrId'],
            "screenshot_path": screenshot_url,
            "photo_path": photo_url
        }

        supabase.table('registrations').insert(insert_payload).execute()
        return jsonify({'success': True, 'registrationId': registration_id}), 201

    except Exception as e:
        print("Registration Error:", str(e))
        return jsonify({'error': f"Failed to register: {str(e)}"}), 500

@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    data = request.json or {}
    if data.get('username') == ADMIN_USERNAME and data.get('password') == ADMIN_PASSWORD:
        session.clear()
        session['is_admin'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def api_admin_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/admin/registrations', methods=['GET'])
def get_admin_registrations():
    if session.get('is_admin') is not True:
        return jsonify({'error': 'Unauthorized'}), 401
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