"""
Auth service - Business logic with bcrypt security
Includes backward compatibility for SHA256 -> bcrypt migration
"""
import random
import hashlib
from typing import Optional
from datetime import datetime

from ..core.security import hash_password, verify_password, create_token_response


def generate_verification_code() -> str:
    """Generate 6-digit verification code"""
    return str(random.randint(100000, 999999))


def is_sha256_hash(password_hash: str) -> bool:
    """Check if a hash is SHA256 (64 hex characters)"""
    if not password_hash or len(password_hash) != 64:
        return False
    return all(c in '0123456789abcdef' for c in password_hash.lower())


def verify_sha256(plain_password: str, hashed_password: str) -> bool:
    """Verify password against SHA256 hash (legacy)"""
    return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password


class AuthService:
    # Class-level dict so verification codes persist across request instances
    _verification_codes: dict = {}

    def __init__(self, db):
        self.users = db["users"]
        self.history = db["history"]

    async def create_user(self, user_data: dict) -> dict:
        """Create new user"""
        # Check existing
        existing = await self.users.find_one({
            "$or": [
                {"email": user_data["email"]},
                {"username": user_data["username"]}
            ]
        })
        if existing:
            return {"success": False, "message": "User already exists"}

        # Hash password and insert
        user_data["password"] = hash_password(user_data["password"])
        await self.users.insert_one(user_data)
        return {"success": True, "message": "User registered successfully"}

    async def login(self, login: str, password: str) -> Optional[dict]:
        """Authenticate user with bcrypt verification and return JWT tokens
        Supports backward compatibility with SHA256 hashes (auto-migrates to bcrypt)
        """
        user = await self.users.find_one({
            "$or": [{"email": login}, {"username": login}]
        })

        if not user:
            return None

        stored_hash = user["password"]
        password_valid = False

        # Check if it's a legacy SHA256 hash (64 hex chars)
        if is_sha256_hash(stored_hash):
            # Verify with SHA256
            password_valid = verify_sha256(password, stored_hash)
            if password_valid:
                # Upgrade to bcrypt for future logins
                new_hash = hash_password(password)
                await self.users.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"password": new_hash}}
                )
                print(f"[OK] Migrated user {user['username']} from SHA256 to bcrypt")
        else:
            # Verify with bcrypt
            password_valid = verify_password(password, stored_hash)

        if not password_valid:
            return None

        # Create JWT token response
        token_response = create_token_response({
            "username": user["username"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "firstName": user.get("firstName", ""),
            "lastName": user.get("lastName", "")
        })

        return {
            "success": True,
            "message": "Login successful",
            **token_response
        }

    async def get_user(self, username: str) -> Optional[dict]:
        """Get user by username"""
        return await self.users.find_one(
            {"username": username},
            {"_id": 0, "password": 0}
        )

    async def update_user(self, username: str, update_data: dict) -> dict:
        """Update user profile"""
        # Check username availability if changing
        if "username" in update_data and update_data["username"] != username:
            existing = await self.users.find_one({"username": update_data["username"]})
            if existing:
                return {"success": False, "message": "Username already taken"}

        result = await self.users.update_one(
            {"username": username},
            {"$set": update_data}
        )
        if result.matched_count == 0:
            return {"success": False, "message": "User not found"}

        return {
            "success": True,
            "message": "User updated successfully",
            "newUsername": update_data.get("username", username)
        }

    async def update_password(self, username: str, old_password: str, new_password: str) -> dict:
        """Update user password with bcrypt (supports legacy SHA256 verification)"""
        user = await self.users.find_one({"username": username})
        if not user:
            return {"success": False, "message": "User not found"}

        stored_hash = user["password"]
        old_password_valid = False

        # Check if legacy SHA256 or bcrypt
        if is_sha256_hash(stored_hash):
            old_password_valid = verify_sha256(old_password, stored_hash)
        else:
            old_password_valid = verify_password(old_password, stored_hash)

        if not old_password_valid:
            return {"success": False, "message": "Invalid old password"}

        # Always use bcrypt for new password
        await self.users.update_one(
            {"username": username},
            {"$set": {"password": hash_password(new_password)}}
        )
        return {"success": True, "message": "Password updated"}

    async def delete_user(self, username: str) -> bool:
        """Delete user"""
        result = await self.users.delete_one({"username": username})
        return result.deleted_count > 0

    def store_verification_code(self, email: str) -> str:
        """Store verification code for password reset"""
        code = generate_verification_code()
        AuthService._verification_codes[email] = code
        return code

    def verify_code(self, email: str, code: str) -> bool:
        """Verify reset code"""
        return AuthService._verification_codes.get(email) == code

    async def reset_password(self, email: str, new_password: str) -> dict:
        """Reset password"""
        result = await self.users.update_one(
            {"email": email},
            {"$set": {"password": hash_password(new_password)}}
        )
        if result.matched_count > 0:
            AuthService._verification_codes.pop(email, None)
            return {"success": True, "message": "Password updated"}
        return {"success": False, "message": "User not found"}

    async def get_all_users(self) -> list:
        """Get all users (admin)"""
        cursor = self.users.find({}, {"_id": 0, "password": 0})
        return await cursor.to_list(length=None)

    # History methods
    async def save_history(self, history_data: dict) -> bool:
        """Save history item"""
        await self.history.insert_one(history_data)
        return True

    async def get_history(self, username: str) -> list:
        """Get user history"""
        cursor = self.history.find({"username": username}, {"_id": 0})
        return await cursor.to_list(length=None)

    async def clear_history(self, username: str) -> int:
        """Clear all user history"""
        result = await self.history.delete_many({"username": username})
        return result.deleted_count

    async def delete_history_item(self, username: str, timestamp: str) -> bool:
        """Delete single history item"""
        result = await self.history.delete_one({
            "username": username,
            "timestamp": timestamp
        })
        return result.deleted_count > 0
