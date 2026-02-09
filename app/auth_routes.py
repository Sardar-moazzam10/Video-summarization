from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app.db_config import user_collection

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    if not all(k in data for k in ("firstName", "lastName", "username", "email", "password", "role")):
        return jsonify({"error": "Missing fields"}), 400

    if user_collection.find_one({"$or": [{"email": data["email"]}, {"username": data["username"]}]}):
        return jsonify({"error": "User already exists"}), 400

    hashed_pw = generate_password_hash(data["password"])
    user = {
        "firstName": data["firstName"],
        "lastName": data["lastName"],
        "username": data["username"],
        "email": data["email"],
        "password": hashed_pw,
        "role": data["role"]
    }

    user_collection.insert_one(user)
    return jsonify({"message": "Signup successful!"}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = user_collection.find_one({
        "$or": [{"email": data["emailOrUsername"]}, {"username": data["emailOrUsername"]}]
    })

    if user and check_password_hash(user["password"], data["password"]):
        return jsonify({"message": "Login successful", "role": user["role"]}), 200
    return jsonify({"error": "Invalid credentials"}), 401
