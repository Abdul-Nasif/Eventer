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
# REST API ENDPOINTS
# -------------------------------------------------------------
@app.route('/api/register', methods=['POST'])
def register():
    try:
        # Support both 'screenshot' and 'receipt' form field names
        screenshot_file = request.files.get('screenshot') or request.files.get('receipt')
        if not screenshot_file:
            return jsonify({'error': 'Payment screenshot is required.'}), 400

        form_data_str = request.form.get('data')
        if not form_data_str:
            return jsonify({'error': 'Metadata packet missing.'}), 400
        
        form_data = json.loads(form_data_str)
        reg_type = form_data.get('regType', 'individual')

        # Check if UTR already exists in database
        check_utr = supabase.table('registrations').select('id').eq('utr_id', form_data['utrId']).execute()
        if len(check_utr.data) > 0:
            return jsonify({'error': 'This UTR ID has already been registered.'}), 400

        # Upload single shared payment receipt
        screenshot_name = secure_filename(screenshot_file.filename)
        screenshot_unique_name = f"receipt-{os.urandom(8).hex()}-{screenshot_name}"
        supabase.storage.from_('receipts').upload(screenshot_unique_name, screenshot_file.read(), {"content-type": screenshot_file.content_type})
        screenshot_url = supabase.storage.from_('receipts').get_public_url(screenshot_unique_name)

        registered_ids = []

        # HANDLE INDIVIDUAL DELEGATE INSERTION
        if reg_type == 'individual':
            photo_file = request.files.get('photo')
            if not photo_file:
                return jsonify({'error': 'Profile photo is required.'}), 400

            photo_name = secure_filename(photo_file.filename)
            photo_unique_name = f"photo-{os.urandom(8).hex()}-{photo_name}"
            supabase.storage.from_('receipts').upload(photo_unique_name, photo_file.read(), {"content-type": photo_file.content_type})
            photo_url = supabase.storage.from_('receipts').get_public_url(photo_unique_name)

            count_res = supabase.table('registrations').select('id', count='exact').execute()
            next_num = str(count_res.count + 101).zfill(6)
            registration_id = f"VMUN-2026-{next_num}"

            # Dynamic preference order resolution
            pref1_committee = form_data.get('pref1_committee', 'UNGA')
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
                "group_id": None
            }
            supabase.table('registrations').insert(insert_payload).execute()
            registered_ids.append(registration_id)

        # HANDLE GROUP BULK INSERTIONS (5 MEMBERS)
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

                count_res = supabase.table('registrations').select('id', count='exact').execute()
                next_num = str(count_res.count + 101).zfill(6)
                registration_id = f"VMUN-2026-{next_num}"

                pref1_committee = member.get('pref1_committee', 'UNGA')
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
                    
                    "utr_id": form_data['utrId'],  # Shared transaction id
                    "screenshot_path": screenshot_url, # Shared receipt image
                    "photo_path": photo_url,
                    "group_id": group_id # Linked group ID
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
app.py