"""Authentication and account business logic with secure recovery flows."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Optional
import uuid

from ..core.config import get_settings
from ..core.security import hash_password, verify_password, create_token_response


settings = get_settings()
RESET_CODE_TTL_MINUTES = 10
RESET_TOKEN_TTL_MINUTES = 10
RESET_MAX_ATTEMPTS = 5


def _utcnow() -> datetime:
    """Naive UTC matches MongoDB's default datetime representation."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _code_digest(email: str, code: str) -> str:
    message = f"{email.strip().lower()}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_sha256_hash(password_hash: str) -> bool:
    if not password_hash or len(password_hash) != 64:
        return False
    return all(c in "0123456789abcdef" for c in password_hash.lower())


def verify_sha256(plain_password: str, hashed_password: str) -> bool:
    candidate = hashlib.sha256(plain_password.encode()).hexdigest()
    return hmac.compare_digest(candidate, hashed_password)


class AuthService:
    def __init__(self, db):
        self.users = db["users"]
        self.history = db["history"]
        self.password_resets = db["password_resets"]

    async def ensure_security_indexes(self) -> None:
        try:
            await self.users.create_index("user_id", unique=True, sparse=True)
            await self.users.create_index("email", unique=True)
            await self.users.create_index("username", unique=True)
            await self.password_resets.create_index("expires_at", expireAfterSeconds=0)
        except (AttributeError, TypeError):
            # Lightweight test doubles do not need index management.
            pass

    async def _generate_unique_username(self, email: str) -> str:
        base = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower()) or "user"
        if len(base) < 3:
            base = f"{base}user"
        candidate, suffix = base, 0
        while await self.users.find_one({"username": candidate}):
            suffix += 1
            candidate = f"{base}{suffix}"
        return candidate

    async def create_user(self, user_data: dict) -> dict:
        """Public registration always creates a normal user."""
        await self.ensure_security_indexes()
        user_data = dict(user_data)
        user_data.pop("role", None)
        email = (user_data.get("email") or "").strip().lower()
        user_data["email"] = email

        name = (user_data.pop("name", "") or "").strip()
        if not user_data.get("firstName"):
            if name:
                parts = name.split()
                user_data["firstName"] = parts[0]
                user_data["lastName"] = " ".join(parts[1:])
            else:
                user_data["firstName"] = email.split("@")[0] if email else "User"
        user_data["lastName"] = user_data.get("lastName") or ""
        if not user_data.get("username"):
            user_data["username"] = await self._generate_unique_username(email)

        existing = await self.users.find_one({
            "$or": [
                {"email": email},
                {"username": user_data["username"]},
            ]
        })
        if existing:
            return {"success": False, "message": "User already exists"}

        user_data.update({
            "user_id": str(uuid.uuid4()),
            "password": hash_password(user_data["password"]),
            "role": "user",
            "isActive": True,
            "auth_version": 0,
            "created_at": _utcnow(),
        })
        await self.users.insert_one(user_data)
        return {"success": True, "message": "User registered successfully"}

    async def login(self, login: str, password: str) -> Optional[dict]:
        user = await self.users.find_one({
            "$or": [
                {"email": login.strip().lower()},
                {"username": login},
            ]
        })
        if not user:
            return None

        stored_hash = user.get("password", "")
        if is_sha256_hash(stored_hash):
            password_valid = verify_sha256(password, stored_hash)
            if password_valid:
                await self.users.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"password": hash_password(password)}},
                )
        else:
            password_valid = verify_password(password, stored_hash)
        if not password_valid:
            return None
        if user.get("isActive") is False:
            return {
                "success": False,
                "account_disabled": True,
                "message": "This account is deactivated. Please contact an administrator.",
            }

        if not user.get("user_id"):
            user["user_id"] = str(uuid.uuid4())
            await self.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"user_id": user["user_id"], "auth_version": 0}},
            )
        token_response = create_token_response({
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "firstName": user.get("firstName", ""),
            "lastName": user.get("lastName", ""),
            "auth_version": int(user.get("auth_version", 0)),
        })
        return {"success": True, "message": "Login successful", **token_response}

    async def get_user(self, username: str) -> Optional[dict]:
        return await self.users.find_one(
            {"username": username}, {"_id": 0, "password": 0}
        )

    async def update_user(self, username: str, update_data: dict) -> dict:
        update_data = dict(update_data)
        if "email" in update_data:
            update_data["email"] = update_data["email"].strip().lower()
        if "username" in update_data and update_data["username"] != username:
            if await self.users.find_one({"username": update_data["username"]}):
                return {"success": False, "message": "Username already taken"}
        if "email" in update_data:
            existing = await self.users.find_one({
                "email": update_data["email"], "username": {"$ne": username}
            })
            if existing:
                return {"success": False, "message": "Email already taken"}
        result = await self.users.update_one(
            {"username": username}, {"$set": update_data}
        )
        if result.matched_count == 0:
            return {"success": False, "message": "User not found"}
        return {
            "success": True,
            "message": "User updated successfully",
            "newUsername": update_data.get("username", username),
        }

    async def update_password(self, username: str, old_password: str, new_password: str) -> dict:
        user = await self.users.find_one({"username": username})
        if not user:
            return {"success": False, "message": "User not found"}
        stored_hash = user.get("password", "")
        valid = (
            verify_sha256(old_password, stored_hash)
            if is_sha256_hash(stored_hash)
            else verify_password(old_password, stored_hash)
        )
        if not valid:
            return {"success": False, "message": "Invalid old password"}
        await self.users.update_one(
            {"username": username},
            {"$set": {"password": hash_password(new_password)}, "$inc": {"auth_version": 1}},
        )
        return {"success": True, "message": "Password updated"}

    async def count_active_admins(self) -> int:
        return await self.users.count_documents({"role": "admin", "isActive": {"$ne": False}})

    async def delete_user(self, username: str) -> dict:
        user = await self.users.find_one({"username": username})
        if not user:
            return {"success": False, "message": "User not found"}
        if user.get("role") == "admin" and await self.count_active_admins() <= 1:
            return {"success": False, "message": "Cannot delete the last active admin account."}
        result = await self.users.delete_one({"username": username})
        return {
            "success": result.deleted_count > 0,
            "message": "User deleted successfully" if result.deleted_count else "Delete failed",
        }

    async def create_password_reset(self, email: str) -> Optional[str]:
        await self.ensure_security_indexes()
        email = email.strip().lower()
        if not await self.users.find_one({"email": email}):
            return None
        code, now = generate_verification_code(), _utcnow()
        await self.password_resets.update_one(
            {"_id": email},
            {
                "$set": {
                    "code_hash": _code_digest(email, code),
                    "attempts_remaining": RESET_MAX_ATTEMPTS,
                    "verified": False,
                    "used": False,
                    "created_at": now,
                    "expires_at": now + timedelta(minutes=RESET_CODE_TTL_MINUTES),
                },
                "$unset": {"token_hash": "", "token_expires_at": ""},
            },
            upsert=True,
        )
        return code

    async def verify_reset_code(self, email: str, code: str) -> Optional[str]:
        email, now = email.strip().lower(), _utcnow()
        challenge = await self.password_resets.find_one({"_id": email})
        if (
            not challenge
            or challenge.get("used")
            or challenge.get("expires_at", now) <= now
            or int(challenge.get("attempts_remaining", 0)) <= 0
        ):
            return None
        if not hmac.compare_digest(_code_digest(email, code), challenge.get("code_hash", "")):
            await self.password_resets.update_one(
                {"_id": email, "attempts_remaining": {"$gt": 0}},
                {"$inc": {"attempts_remaining": -1}},
            )
            return None

        token = secrets.token_urlsafe(32)
        await self.password_resets.update_one(
            {"_id": email, "used": False},
            {
                "$set": {
                    "verified": True,
                    "token_hash": _token_digest(token),
                    "token_expires_at": now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
                    "expires_at": now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
                },
                "$unset": {"code_hash": ""},
            },
        )
        return token

    async def reset_password(self, reset_token: str, new_password: str) -> dict:
        now, token_hash = _utcnow(), _token_digest(reset_token)
        challenge = await self.password_resets.find_one({
            "token_hash": token_hash,
            "verified": True,
            "used": False,
            "token_expires_at": {"$gt": now},
        })
        if not challenge:
            return {"success": False, "message": "Invalid or expired reset token"}
        consumed = await self.password_resets.update_one(
            {"_id": challenge["_id"], "token_hash": token_hash, "used": False},
            {"$set": {"used": True, "used_at": now}},
        )
        if consumed.modified_count != 1:
            return {"success": False, "message": "Invalid or expired reset token"}
        result = await self.users.update_one(
            {"email": challenge["_id"]},
            {"$set": {"password": hash_password(new_password)}, "$inc": {"auth_version": 1}},
        )
        if result.matched_count != 1:
            return {"success": False, "message": "Invalid or expired reset token"}
        return {"success": True, "message": "Password updated"}

    async def get_all_users(self) -> list:
        return await self.users.find({}, {"_id": 0, "password": 0}).to_list(length=None)

    async def toggle_user_status(self, username: str) -> dict:
        user = await self.users.find_one({"username": username})
        if not user:
            return {"success": False, "message": "User not found"}
        new_status = not user.get("isActive", True)
        if user.get("role") == "admin" and not new_status and await self.count_active_admins() <= 1:
            return {"success": False, "message": "Cannot deactivate the last active admin."}
        await self.users.update_one(
            {"username": username},
            {"$set": {"isActive": new_status}, "$inc": {"auth_version": 1}},
        )
        return {
            "success": True,
            "isActive": new_status,
            "message": f"User {'activated' if new_status else 'deactivated'} successfully",
        }

    async def admin_create_user(self, user_data: dict) -> dict:
        email = (user_data.get("email") or "").strip().lower()
        username = (user_data.get("username") or "").strip()
        password = user_data.get("password") or ""
        role = user_data.get("role", "user")
        if not email or not password or not username:
            return {"success": False, "message": "Email, username, and password are required"}
        if len(password) < 6:
            return {"success": False, "message": "Password must be at least 6 characters"}
        if role not in ("user", "admin"):
            return {"success": False, "message": "Invalid role"}
        if await self.users.find_one({"$or": [{"email": email}, {"username": username}]}):
            return {"success": False, "message": "Email or username already exists"}
        await self.users.insert_one({
            "user_id": str(uuid.uuid4()),
            "firstName": (user_data.get("firstName") or email.split("@")[0]).strip(),
            "lastName": (user_data.get("lastName") or "").strip(),
            "username": username,
            "email": email,
            "password": hash_password(password),
            "role": role,
            "isActive": True,
            "auth_version": 0,
            "created_at": _utcnow(),
        })
        return {"success": True, "message": f"User '{username}' created successfully as {role}"}

    async def admin_update_user(self, username: str, update_data: dict) -> dict:
        user = await self.users.find_one({"username": username})
        if not user:
            return {"success": False, "message": "User not found"}
        clean = {}
        new_username = (update_data.get("username") or "").strip()
        new_email = (update_data.get("email") or "").strip().lower()
        new_role = update_data.get("role")
        if new_username and new_username != username:
            if await self.users.find_one({"username": new_username}):
                return {"success": False, "message": "Username is already taken"}
            clean["username"] = new_username
        if new_email and new_email != user.get("email"):
            if await self.users.find_one({"email": new_email}):
                return {"success": False, "message": "Email is already in use"}
            clean["email"] = new_email
        for field in ("firstName", "lastName"):
            if field in update_data:
                clean[field] = str(update_data[field]).strip()
        if new_role in ("user", "admin"):
            if user.get("role") == "admin" and new_role != "admin" and await self.count_active_admins() <= 1:
                return {"success": False, "message": "Platform must retain one active admin."}
            clean["role"] = new_role
        if "isActive" in update_data:
            new_active = bool(update_data["isActive"])
            if user.get("role") == "admin" and not new_active and await self.count_active_admins() <= 1:
                return {"success": False, "message": "Cannot deactivate the last active admin."}
            clean["isActive"] = new_active
        if clean:
            update = {"$set": clean}
            if (
                ("role" in clean and clean["role"] != user.get("role", "user"))
                or ("isActive" in clean and clean["isActive"] != user.get("isActive", True))
            ):
                update["$inc"] = {"auth_version": 1}
            await self.users.update_one({"username": username}, update)
        return {
            "success": True,
            "message": "User updated successfully",
            "newUsername": clean.get("username", username),
        }

    async def get_platform_stats(self) -> dict:
        week_ago = _utcnow() - timedelta(days=7)
        total_users = await self.users.count_documents({})
        active_users = await self.users.count_documents({"isActive": {"$ne": False}})
        admin_users = await self.users.count_documents({"role": "admin"})
        new_this_week = await self.users.count_documents({"created_at": {"$gte": week_ago}})
        totals = {
            name: await self.history.count_documents({"type": kind})
            for name, kind in (
                ("total_searches", "search"),
                ("total_watches", "watch"),
                ("total_merges", "merge"),
                ("total_transcripts", "transcript-view"),
            )
        }
        today = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        cursor = self.history.aggregate([
            {"$match": {"timestamp": {"$gte": today}}},
            {"$group": {"_id": "$username"}},
            {"$count": "count"},
        ])
        rows = await cursor.to_list(length=1)
        return {
            "users": {
                "total": total_users,
                "active": active_users,
                "inactive": total_users - active_users,
                "admins": admin_users,
                "new_this_week": new_this_week,
                "active_today": rows[0]["count"] if rows else 0,
            },
            "activity": {**totals, "total_actions": sum(totals.values())},
        }

    async def save_history(self, history_data: dict) -> bool:
        await self.history.insert_one(history_data)
        return True

    async def get_history(self, username: str) -> list:
        return await self.history.find({"username": username}, {"_id": 0}).to_list(length=None)

    async def clear_history(self, username: str) -> int:
        return (await self.history.delete_many({"username": username})).deleted_count

    async def delete_history_item(self, username: str, timestamp) -> bool:
        result = await self.history.delete_one({"username": username, "timestamp": timestamp})
        return result.deleted_count > 0
