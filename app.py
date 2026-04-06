import os
from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import database.provider as db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'apple-starlight-secret')

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
async def upload_file():
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to prevent caching issues
        import time
        filename = f"{int(time.time())}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'url': f'/static/uploads/{filename}'})
    return jsonify({'error': 'Invalid file type'}), 400

# Mock RBAC check
ADMIN_ID = os.getenv('ADMIN_ID', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS', 'password123')

def is_authorized():
    return session.get('authorized', False)

@app.before_request
async def initialize():
    if not os.path.exists('org_chart.sqlite'):
        await db.init_db()

@app.route('/')
async def index():
    return render_template('index.html')

@app.route('/api/auth', methods=['POST'])
async def auth():
    data = request.json
    if data.get('id') == ADMIN_ID and data.get('password') == ADMIN_PASS:
        session['authorized'] = True
        return jsonify({'success': True, 'message': 'Authorized'})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
async def logout():
    session.pop('authorized', None)
    return jsonify({'success': True})

@app.route('/api/employees')
async def get_employees():
    manager_id = request.args.get('manager_id')
    if manager_id == 'null' or manager_id == '':
        manager_id = None
    else:
        try:
            manager_id = int(manager_id)
        except:
            manager_id = None
    
    employees = await db.get_employees(manager_id)
    return jsonify(employees)

@app.route('/api/search')
async def search():
    query = request.args.get('q', '')
    if not query:
        return jsonify({'lineage': [], 'results': []})
    
    results = await db.search_employees(query)
    # If a single perfect match is found, also get lineage
    lineage = []
    if len(results) == 1:
        lineage = await db.get_lineage(results[0]['id'])
        
    return jsonify({
        'results': results,
        'lineage': lineage
    })

@app.route('/api/employees/<int:employee_id>/reports')
async def get_reports(employee_id):
    employees = await db.get_employees(employee_id)
    return jsonify(employees)

@app.route('/api/employees', methods=['POST'])
async def add_employee():
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    new_id = await db.add_employee(data)
    return jsonify({'success': True, 'id': new_id})

@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
async def update_employee(employee_id):
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    await db.update_employee(employee_id, data)
    return jsonify({'success': True})

@app.route('/api/employees/<int:employee_id>', methods=['DELETE'])
async def delete_employee(employee_id):
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
    
    await db.delete_employee(employee_id)
    return jsonify({'success': True})

@app.route('/api/auth/status')
async def auth_status():
    return jsonify({'authorized': is_authorized()})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
