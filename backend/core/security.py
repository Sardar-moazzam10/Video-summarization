"""
Security Module - Production-grade authentication

Features:
- bcrypt password hashing (industry standard)
- JWT token generation & validation
- Rate limiting helpers
- Security utilities
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import uuid
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import get_settings

settings = get_settings()

# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Bearer scheme
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


# =====================================================
# PASSWORD HASHING
# =====================================================

def hash_password(password: str) -> str:
    """
    Hash password using bcrypt.

    bcrypt automatically handles:
    - Salt generation
    - Multiple rounds (default 12)
    - Timing attack protection
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# =====================================================
# JWT TOKENS
# =====================================================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT access token.

    Args:
        data: Payload data (user_id, username, role, etc.)
        expires_delta: Token lifetime (default 24 hours)

    Returns:
        Encoded JWT string
    """
    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    )

    to_encode.update({
        "exp": expire,
        "iat": now,
        "type": "access"
    })

    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT refresh token (longer lived)."""
    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(days=7)
    )

    to_encode.update({
        "exp": expire,
        "iat": now,
        "type": "refresh"
    })

    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode JWT token.

    Returns:
        Decoded payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def create_media_token(job_id: str, media_kind: str, user_id: str) -> str:
    """Create a short-lived token scoped to one job artifact.

    Browser media elements cannot attach an Authorization header, so protected
    audio/video/subtitle URLs use this narrowly scoped token instead of making
    the files public or putting the normal access token in a URL.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "job_id": job_id,
        "media_kind": media_kind,
        "type": "media",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_media_token(token: str, job_id: str, media_kind: str) -> bool:
    payload = verify_token(token)
    return bool(
        payload
        and payload.get("type") == "media"
        and payload.get("job_id") == job_id
        and payload.get("media_kind") == media_kind
        and payload.get("sub")
    )


# =====================================================
# FASTAPI DEPENDENCIES
# =====================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> Dict[str, Any]:
    """
    FastAPI dependency to get current authenticated user.

    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user": user["username"]}
    """
    token = credentials.credentials
    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=401,
            detail="Invalid token type"
        )

    return await _resolve_active_user(payload)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional)
) -> Optional[Dict[str, Any]]:
    """
    Optional authentication - returns None if no token.
    Useful for routes that work both authenticated and anonymously.
    """
    if not credentials:
        return None

    payload = verify_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return await _resolve_active_user(payload)


async def _resolve_active_user(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve token identity against current DB state.

    Roles and account status are never trusted solely from a long-lived token:
    demotion or deactivation takes effect on the next request.
    """
    subject = str(payload.get("sub") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    from .database import get_database
    db = await get_database()
    user = await db["users"].find_one({"user_id": subject})
    if not user:
        # Transitional support for tokens issued before immutable user IDs were
        # introduced. A successful login backfills user_id and issues a new JWT.
        user = await db["users"].find_one({"username": subject})
    if not user or user.get("isActive") is False:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    if int(payload.get("auth_version", 0)) != int(user.get("auth_version", 0)):
        raise HTTPException(status_code=401, detail="Session is no longer valid")

    if not user.get("user_id"):
        user["user_id"] = str(uuid.uuid4())
        await db["users"].update_one(
            {"_id": user["_id"]},
            {"$set": {"user_id": user["user_id"], "auth_version": int(user.get("auth_version", 0))}},
        )

    resolved = payload.copy()
    resolved.update({
        "sub": str(user["user_id"]),
        "user_id": str(user["user_id"]),
        "username": user.get("username"),
        "email": user.get("email"),
        "role": user.get("role", "user"),
    })
    return resolved


def require_role(required_role: str):
    """
    Factory for role-based access control.

    Usage:
        @router.get("/admin-only")
        async def admin_route(user: dict = Depends(require_role("admin"))):
            ...
    """
    async def role_checker(
        user: Dict[str, Any] = Depends(get_current_user)
    ) -> Dict[str, Any]:
        if user.get("role") != required_role:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{required_role}' required"
            )
        return user

    return role_checker


# =====================================================
# TOKEN RESPONSE HELPER
# =====================================================

def create_token_response(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create standard token response for login/signup.

    Returns:
        {
            "access_token": "...",
            "refresh_token": "...",
            "token_type": "bearer",
            "expires_in": 86400,
            "user": { ... }
        }
    """
    token_data = {
        "sub": user_data["user_id"],
        "user_id": user_data["user_id"],
        "username": user_data["username"],
        "email": user_data.get("email"),
        "role": user_data.get("role", "user"),
        "auth_version": int(user_data.get("auth_version", 0)),
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": user_data["user_id"]})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        "user": {
            "user_id": user_data["user_id"],
            "username": user_data["username"],
            "email": user_data.get("email"),
            "firstName": user_data.get("firstName"),
            "lastName": user_data.get("lastName"),
            "role": user_data.get("role", "user")
        }
    }
