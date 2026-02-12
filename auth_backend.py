from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from flask_mail import Mail, Message
from dotenv import load_dotenv
import hashlib
import random
import os

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# ===== MongoDB Configuration =====
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "user-auth")
client = MongoClient(MONGODB_URI)
db = client[MONGODB_DATABASE]
users = db['users']
history = db['history']

# ===== Email Configuration =====
app.config['MAIL_SERVER'] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.getenv("MAIL_PORT", "587"))
app.config['MAIL_USE_TLS'] = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME", "")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD", "")
mail = Mail(app)

verification_codes = {}

# ===== Helper =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ===== AUTH =====
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    if users.find_one({'$or': [{'email': data['email']}, {'username': data['username']}] }):
        return jsonify({'success': False, 'message': 'User already exists.'}), 409
    user = {
        'firstName': data['firstName'],
        'lastName': data['lastName'],
        'email': data['email'],
        'username': data['username'],
        'password': hash_password(data['password']),
        'role': data.get('role', 'user')
    }
    users.insert_one(user)
    return jsonify({'success': True, 'message': 'User registered successfully.'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = users.find_one({
        '$or': [{'email': data['login']}, {'username': data['login']}],
        'password': hash_password(data['password'])
    })
    if user:
        return jsonify({
            'success': True,
            'message': 'Login successful.',
            'role': user['role'],
            'username': user['username'],
            'firstName': user.get('firstName', ''),
            'email': user['email']
        })
    return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401

# ===== PASSWORD RESET =====
@app.route('/api/send-verification-code', methods=['POST'])
def send_verification_code():
    data = request.json
    email = data.get('email')
    user = users.find_one({'email': email})
    if not user:
        return jsonify({'success': False, 'message': 'Email not found.'}), 404
    code = str(random.randint(100000, 999999))
    verification_codes[email] = code
    msg = Message('Your Password Reset Code', sender=app.config['MAIL_USERNAME'], recipients=[email])
    msg.body = f'Your verification code is: {code}'
    mail.send(msg)
    return jsonify({'success': True, 'message': 'Verification code sent.'})

@app.route('/api/verify-code', methods=['POST'])
def verify_code():
    data = request.json
    email = data.get('email')
    code = data.get('code')
    if verification_codes.get(email) == code:
        return jsonify({'success': True, 'message': 'Code verified.'})
    return jsonify({'success': False, 'message': 'Invalid or expired code.'}), 400

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.json
    email = data.get('email')
    new_password = hash_password(data.get('password'))
    result = users.update_one({'email': email}, {'$set': {'password': new_password}})
    if result.matched_count > 0:
        return jsonify({'success': True, 'message': 'Password updated.'})
    return jsonify({'success': False, 'message': 'User not found.'}), 404

# ===== PROFILE =====
@app.route('/api/user/<username>', methods=['GET'])
def get_user(username):
    user = users.find_one({'username': username}, {'_id': 0, 'password': 0})
    return jsonify(user) if user else jsonify({'error': 'User not found'}), 404



@app.route('/api/user/update/<username>', methods=['PUT'])
def update_user(username):
    data = request.json
    allowed_fields = ['firstName', 'lastName', 'email', 'username', 'role']
    update_data = {k: data[k] for k in allowed_fields if k in data}

    # If the username is being changed, check for duplicates
    if 'username' in update_data and update_data['username'] != username:
        if users.find_one({'username': update_data['username']}):
            return jsonify({'success': False, 'message': 'Username already taken.'}), 409

    result = users.update_one({'username': username}, {'$set': update_data})

    if result.matched_count == 0:
        return jsonify({'success': False, 'message': 'User not found.'}), 404

    return jsonify({
        'success': True,
        'message': 'User updated successfully.',
        'newUsername': update_data.get('username', username)
    })






@app.route('/api/user/delete/<username>', methods=['DELETE'])
def delete_user(username):
    result = users.delete_one({'username': username})
    return jsonify({'success': result.deleted_count > 0})

@app.route('/api/user/update-password/<username>', methods=['PUT'])
def update_password(username):
    data = request.json
    old_password = data.get('oldPassword')
    new_password = data.get('newPassword')
    user = users.find_one({'username': username})
    if not user or user['password'] != hash_password(old_password):
        return jsonify({'success': False, 'message': 'Invalid old password.'}), 401
    result = users.update_one({'username': username}, {'$set': {'password': hash_password(new_password)}})
    return jsonify({'success': result.modified_count > 0})

# ===== HISTORY ROUTES =====
@app.route('/api/user-history', methods=['POST'])
def save_history():
    data = request.json
    if not all(k in data for k in ("username", "type", "timestamp")):
        return jsonify({"error": "Missing required fields"}), 400
    history.insert_one(data)
    return jsonify({"success": True})

@app.route('/api/user-history/<username>', methods=['GET'])
def get_history(username):
    records = list(history.find({'username': username}, {'_id': 0}))
    return jsonify(records)

@app.route('/api/user-history/delete/<username>', methods=['DELETE'])
def clear_history(username):
    result = history.delete_many({'username': username})
    return jsonify({'success': True, 'deleted': result.deleted_count})

@app.route('/api/user-history/delete-one', methods=['DELETE'])
def delete_history_item():
    data = request.json
    username = data.get('username')
    timestamp = data.get('timestamp')
    if not username or not timestamp:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    result = history.delete_one({'username': username, 'timestamp': timestamp})
    return jsonify({'success': result.deleted_count > 0})


# ===== USER LIST =====
@app.route('/api/users', methods=['GET'])
def get_all_users():
    try:
        all_users = list(users.find({}, {'_id': 0, 'password': 0}))
        return jsonify(all_users)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500







# ===== SERVER START =====
if __name__ == '__main__':
    from waitress import serve
    print("[OK] Waitress running on http://127.0.0.1:5000")
    serve(app, host='127.0.0.1', port=5000)


