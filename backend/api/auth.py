"""
Auth API routes - FastAPI router
"""
from fastapi import APIRouter, HTTPException, Depends
from ..models.user import (
    UserCreate, UserLogin, UserResponse, UserUpdate,
    PasswordUpdate, PasswordReset, VerificationCode, HistoryItem
)
from ..services.auth_service import AuthService
from ..services.email_service import send_verification_email
from ..core.database import get_database

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def get_auth_service():
    db = await get_database()
    return AuthService(db)


# ===== AUTH =====
@router.post("/signup")
async def signup(user: UserCreate, service: AuthService = Depends(get_auth_service)):
    result = await service.create_user(user.model_dump())
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/login")
async def login(credentials: UserLogin, service: AuthService = Depends(get_auth_service)):
    result = await service.login(credentials.login, credentials.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return result


# ===== PASSWORD RESET =====
@router.post("/send-verification-code")
async def send_verification_code(
    data: dict,
    service: AuthService = Depends(get_auth_service)
):
    email = data.get("email")
    user = await service.users.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")

    code = service.store_verification_code(email)
    sent = await send_verification_email(email, code)
    if not sent:
        raise HTTPException(status_code=500, detail="Failed to send verification email")
    return {"success": True, "message": "Verification code sent"}


@router.post("/verify-code")
async def verify_code(data: VerificationCode, service: AuthService = Depends(get_auth_service)):
    if service.verify_code(data.email, data.code):
        return {"success": True, "message": "Code verified"}
    raise HTTPException(status_code=400, detail="Invalid or expired code")


@router.post("/reset-password")
async def reset_password(data: PasswordReset, service: AuthService = Depends(get_auth_service)):
    result = await service.reset_password(data.email, data.password)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ===== PROFILE =====
@router.get("/user/{username}")
async def get_user(username: str, service: AuthService = Depends(get_auth_service)):
    user = await service.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/user/update/{username}")
async def update_user(
    username: str,
    data: UserUpdate,
    service: AuthService = Depends(get_auth_service)
):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    result = await service.update_user(username, update_data)
    if not result["success"]:
        raise HTTPException(
            status_code=409 if "taken" in result["message"] else 404,
            detail=result["message"]
        )
    return result


@router.delete("/user/delete/{username}")
async def delete_user(username: str, service: AuthService = Depends(get_auth_service)):
    success = await service.delete_user(username)
    return {"success": success}


@router.put("/user/update-password/{username}")
async def update_password(
    username: str,
    data: PasswordUpdate,
    service: AuthService = Depends(get_auth_service)
):
    result = await service.update_password(username, data.oldPassword, data.newPassword)
    if not result["success"]:
        raise HTTPException(status_code=401, detail=result["message"])
    return result


# ===== HISTORY =====
@router.post("/user-history")
async def save_history(data: HistoryItem, service: AuthService = Depends(get_auth_service)):
    await service.save_history(data.model_dump())
    return {"success": True}


@router.get("/user-history/{username}")
async def get_history(username: str, service: AuthService = Depends(get_auth_service)):
    return await service.get_history(username)


@router.delete("/user-history/delete/{username}")
async def clear_history(username: str, service: AuthService = Depends(get_auth_service)):
    deleted = await service.clear_history(username)
    return {"success": True, "deleted": deleted}


@router.delete("/user-history/delete-one")
async def delete_history_item(data: dict, service: AuthService = Depends(get_auth_service)):
    success = await service.delete_history_item(data["username"], data["timestamp"])
    return {"success": success}


# ===== ADMIN =====
@router.get("/users")
async def get_all_users(service: AuthService = Depends(get_auth_service)):
    return await service.get_all_users()
