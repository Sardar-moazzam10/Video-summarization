"""Authentication, account, history and admin API routes."""

from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from ..core.database import get_database
from ..core.security import get_current_user, require_role
from ..models.user import (
    HistoryItem,
    PasswordReset,
    PasswordUpdate,
    UserCreate,
    UserLogin,
    UserUpdate,
    VerificationCode,
)
from ..services.auth_service import AuthService
from ..services.email_service import send_verification_email


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
RESET_REQUEST_MESSAGE = (
    "If an account exists for that email, a verification code has been sent."
)


class ResetRequest(BaseModel):
    email: EmailStr


async def get_auth_service():
    return AuthService(await get_database())


def _require_self_or_admin(username: str, principal: Dict[str, Any]) -> None:
    if principal.get("role") != "admin" and principal.get("username") != username:
        raise HTTPException(status_code=403, detail="You cannot access this account")


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
    if result.get("success") is False:
        raise HTTPException(status_code=403, detail=result.get("message"))
    return result


@router.post("/send-verification-code")
async def send_verification_code(
    data: ResetRequest,
    background_tasks: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
):
    # The public response deliberately does not reveal account existence.
    code = await service.create_password_reset(str(data.email))
    if code:
        # Delivery happens after the generic response, reducing timing-based
        # account enumeration and keeping SMTP latency off the request path.
        background_tasks.add_task(send_verification_email, str(data.email), code)
    return {"success": True, "message": RESET_REQUEST_MESSAGE}


@router.post("/verify-code")
async def verify_code(
    data: VerificationCode,
    service: AuthService = Depends(get_auth_service),
):
    reset_token = await service.verify_reset_code(str(data.email), data.code)
    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return {
        "success": True,
        "message": "Code verified",
        "reset_token": reset_token,
    }


@router.post("/reset-password")
async def reset_password(
    data: PasswordReset,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.reset_password(data.reset_token, data.password)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/user/{username}")
async def get_user(
    username: str,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    _require_self_or_admin(username, principal)
    user = await service.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/user/update/{username}")
async def update_user(
    username: str,
    data: UserUpdate,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    _require_self_or_admin(username, principal)
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    result = await service.update_user(username, update_data)
    if not result["success"]:
        raise HTTPException(
            status_code=409 if "taken" in result["message"] else 404,
            detail=result["message"],
        )
    return result


@router.delete("/user/delete/{username}")
async def delete_user(
    username: str,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    _require_self_or_admin(username, principal)
    result = await service.delete_user(username)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.put("/user/update-password/{username}")
async def update_password(
    username: str,
    data: PasswordUpdate,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    # Admins must not change another user's password using an old-password flow.
    if principal.get("username") != username:
        raise HTTPException(status_code=403, detail="You cannot change this password")
    result = await service.update_password(username, data.oldPassword, data.newPassword)
    if not result["success"]:
        raise HTTPException(status_code=401, detail=result["message"])
    return result


@router.post("/user-history")
async def save_history(
    data: HistoryItem,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    _require_self_or_admin(data.username, principal)
    await service.save_history(data.model_dump())
    return {"success": True}


@router.get("/user-history/{username}")
async def get_history(
    username: str,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    _require_self_or_admin(username, principal)
    return await service.get_history(username)


@router.delete("/user-history/delete/{username}")
async def clear_history(
    username: str,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    _require_self_or_admin(username, principal)
    return {"success": True, "deleted": await service.clear_history(username)}


@router.delete("/user-history/delete-one")
async def delete_history_item(
    data: dict,
    service: AuthService = Depends(get_auth_service),
    principal: Dict[str, Any] = Depends(get_current_user),
):
    username = data.get("username", "")
    _require_self_or_admin(username, principal)
    return {
        "success": await service.delete_history_item(username, data.get("timestamp"))
    }


@router.get("/users")
async def get_all_users(
    service: AuthService = Depends(get_auth_service),
    _admin: Dict[str, Any] = Depends(require_role("admin")),
):
    return await service.get_all_users()


@router.get("/admin/stats")
async def get_platform_stats(
    service: AuthService = Depends(get_auth_service),
    _admin: Dict[str, Any] = Depends(require_role("admin")),
):
    return await service.get_platform_stats()


@router.patch("/admin/toggle-user/{username}")
async def toggle_user_status(
    username: str,
    service: AuthService = Depends(get_auth_service),
    current_admin: Dict[str, Any] = Depends(require_role("admin")),
):
    if username == current_admin.get("username"):
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    result = await service.toggle_user_status(username)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.put("/admin/user/{username}")
async def admin_update_user(
    username: str,
    data: dict,
    service: AuthService = Depends(get_auth_service),
    _admin: Dict[str, Any] = Depends(require_role("admin")),
):
    result = await service.admin_update_user(username, data)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/admin/create-user")
async def admin_create_user(
    data: dict,
    service: AuthService = Depends(get_auth_service),
    _admin: Dict[str, Any] = Depends(require_role("admin")),
):
    result = await service.admin_create_user(data)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result
