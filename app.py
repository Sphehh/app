import os
import json
import time
import hashlib
import hmac
import sqlite3
import secrets
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify,
    session, redirect, url_for
)
from flask_cors import CORS
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
CORS(app, supports_credentials=True)

# ---------- Database setup (SQLite) ----------
DATABASE = 'data.db'

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                credits INTEGER DEFAULT 2,
                role TEXT DEFAULT 'user'
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                template_id TEXT,
                result_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.commit()
init_db()

# ---------- Auth helpers ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        return f(*args, **kwargs)
    return decorated

# ---------- Frontend ----------
@app.route('/')
def index():
    return render_template('index.html')

# ---------- Auth endpoints ----------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    db = get_db()
    # Check existing user
    user = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if user:
        return jsonify({'error': 'Email already registered'}), 409

    # Hash password (simple sha256, not production-grade but works)
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    db.execute('INSERT INTO users (email, password_hash, credits) VALUES (?, ?, 2)', (email, password_hash))
    db.commit()
    return jsonify({'message': 'Registration successful'}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if user['password_hash'] != password_hash:
        return jsonify({'error': 'Invalid credentials'}), 401

    session['user_id'] = user['id']
    session['email'] = user['email']
    session['role'] = user['role']
    return jsonify({'message': 'Logged in', 'user': {'id': user['id'], 'email': user['email'], 'role': user['role']}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me')
def get_current_user():
    if 'user_id' not in session:
        return jsonify({'logged_in': False})
    return jsonify({
        'logged_in': True,
        'user': {
            'id': session['user_id'],
            'email': session['email'],
            'role': session['role']
        }
    })

# ---------- Credits ----------
@app.route('/api/credits', methods=['GET'])
@login_required
def get_credits():
    db = get_db()
    user = db.execute('SELECT credits FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return jsonify({'credits': user['credits']})

# ---------- Generate flyer (replaces Netlify generate-flyer.js) ----------
@app.route('/api/generate', methods=['POST'])
@login_required
def generate_flyer():
    # Check credits
    db = get_db()
    user = db.execute('SELECT credits FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if user['credits'] < 2:
        return jsonify({'error': 'Insufficient credits'}), 402

    data = request.json
    prompt_text = data.get('prompt')
    ratio = data.get('ratio', '2:3')
    resolution = data.get('resolution', '2K')

    if not prompt_text:
        return jsonify({'error': 'Prompt is required'}), 400

    # Call PiAPI
    headers = {
        'x-api-key': os.environ.get('PIAPI_KEY'),
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'gemini',
        'task_type': 'nano-banana-2',
        'input': {
            'prompt': prompt_text,
            'output_format': 'png',
            'aspect_ratio': ratio,
            'resolution': resolution
        }
    }
    try:
        resp = requests.post('https://api.piapi.ai/api/v1/task', json=payload, headers=headers)
        if resp.status_code != 200:
            return jsonify({'error': f'PiAPI error: {resp.text}'}), 500
        pi_data = resp.json()
        if pi_data.get('code') != 200:
            return jsonify({'error': pi_data.get('message', 'PiAPI task creation failed')}), 500
        task_id = pi_data['data']['task_id']

        # Poll for result (max 3 minutes)
        image_url = None
        for _ in range(45):  # 45 * 4s = 3min
            time.sleep(4)
            poll_resp = requests.get(f'https://api.piapi.ai/api/v1/task/{task_id}', headers=headers)
            poll_data = poll_resp.json()
            status = poll_data.get('data', {}).get('status') or poll_data.get('status')
            if status == 'completed':
                image_url = poll_data['data']['output']['image_url']
                break
            elif status == 'failed':
                return jsonify({'error': 'Generation failed'}), 500
        if not image_url:
            return jsonify({'error': 'Timed out'}), 500

        # Deduct credits
        new_credits = user['credits'] - 2
        db.execute('UPDATE users SET credits = ? WHERE id = ?', (new_credits, session['user_id']))
        # Save project
        db.execute('INSERT INTO projects (user_id, template_id, result_url) VALUES (?, ?, ?)',
                   (session['user_id'], data.get('template_id', ''), image_url))
        db.commit()

        return jsonify({'image': image_url, 'credits': new_credits})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------- Projects ----------
@app.route('/api/projects')
@login_required
def get_projects():
    db = get_db()
    rows = db.execute('SELECT id, template_id, result_url, created_at FROM projects WHERE user_id = ? ORDER BY created_at DESC',
                      (session['user_id'],)).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- PayFast (simplified) ----------
@app.route('/api/create-payfast-order', methods=['POST'])
@login_required
def create_payfast_order():
    data = request.json
    amount = data.get('amount')  # number of credits
    if not amount:
        return jsonify({'error': 'Missing amount'}), 400

    merchant_id = os.environ.get('PAYFAST_MERCHANT_ID', '10000100')
    merchant_key = os.environ.get('PAYFAST_MERCHANT_KEY', '46f0cd694581a')
    passphrase = os.environ.get('PAYFAST_PASSPHRASE', '')
    notify_url = request.host_url.rstrip('/') + '/api/payfast-itn'
    return_url = request.host_url.rstrip('/') + '/dashboard'

    pf_data = {
        'merchant_id': merchant_id,
        'merchant_key': merchant_key,
        'return_url': return_url,
        'cancel_url': return_url,
        'notify_url': notify_url,
        'name_first': session.get('email', 'Customer'),
        'email_address': session.get('email', ''),
        'm_payment_id': f"{session['user_id']}_{int(time.time())}",
        'amount': f"{(int(amount) * 9.99):.2f}",
        'item_name': f"{amount} Credits",
        'custom_str1': str(session['user_id'])
    }

    # Generate PayFast signature
    pf_param_string = '&'.join(
        f"{k}={pf_data[k].replace(' ', '+')}" for k in sorted(pf_data.keys()) if k != 'signature'
    )
    if passphrase:
        pf_param_string += f"&passphrase={passphrase}"
    signature = hashlib.md5(pf_param_string.encode()).hexdigest()
    pf_data['signature'] = signature

    # Build form HTML for submission
    form_fields = ''.join(f'<input type="hidden" name="{k}" value="{v}">' for k,v in pf_data.items())
    form_html = f'<form action="https://www.payfast.co.za/eng/process" method="post" id="payfast-form">{form_fields}</form>'
    return jsonify({'form': form_html, 'fields': pf_data})

@app.route('/api/payfast-itn', methods=['POST'])
def payfast_itn():
    # Validate signature
    pf_data = request.form.to_dict()
    pf_param_string = '&'.join(
        f"{k}={pf_data[k].replace(' ', '+')}" for k in sorted(pf_data.keys()) if k != 'signature'
    )
    passphrase = os.environ.get('PAYFAST_PASSPHRASE', '')
    if passphrase:
        pf_param_string += f"&passphrase={passphrase}"
    expected_sig = hashlib.md5(pf_param_string.encode()).hexdigest()
    if expected_sig != pf_data.get('signature'):
        return 'Invalid signature', 400

    # Update credits
    user_id = pf_data.get('custom_str1')
    try:
        credits_purchased = int(pf_data.get('item_name', '0').split()[0])
    except:
        credits_purchased = 0

    db = get_db()
    user = db.execute('SELECT credits FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        db.execute('UPDATE users SET credits = ? WHERE id = ?',
                   (user['credits'] + credits_purchased, user_id))
        db.commit()
    return 'OK', 200

# ---------- Admin endpoints (no separate admin.html needed; admin can manage via API) ----------
@app.route('/api/admin/prompts', methods=['GET'])
@login_required
def admin_get_prompts():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    with open('prompts.json') as f:
        return jsonify(json.load(f))

@app.route('/api/admin/prompts', methods=['PUT'])
@login_required
def admin_update_prompts():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    with open('prompts.json', 'w') as f:
        json.dump(data, f, indent=2)
    return jsonify({'message': 'Prompts updated'})

@app.route('/api/admin/users', methods=['GET'])
@login_required
def admin_get_users():
    if session.get('role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    db = get_db()
    users = db.execute('SELECT id, email, credits, role FROM users').fetchall()
    return jsonify([dict(u) for u in users])

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@login_required
def admin_update_user(user_id):
    if session.get('role') != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    data = request.json
    db = get_db()
    # Update credits or role
    if 'credits' in data:
        db.execute('UPDATE users SET credits = ? WHERE id = ?', (data['credits'], user_id))
    if 'role' in data:
        db.execute('UPDATE users SET role = ? WHERE id = ?', (data['role'], user_id))
    db.commit()
    return jsonify({'message': 'User updated'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
