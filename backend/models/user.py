"""
User models - Pydantic schemas
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import datetime


class UserCreate(BaseModel):
    firstName: str = Field(..., min_length=1, max_length=50)
    lastName: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=6)
    role: Literal["user", "admin"] = "user"


class UserLogin(BaseModel):
    login: str  # username or email
    password: str


class UserResponse(BaseModel):
    firstName: str
    lastName: str
    email: str
    username: str
    role: str


class UserUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[EmailStr] = None
    username: Optional[str] = None


class PasswordUpdate(BaseModel):
    oldPassword: str
    newPassword: str = Field(..., min_length=6)


class PasswordReset(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class VerificationCode(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class HistoryItem(BaseModel):
    username: str
    type: Literal["watch", "search", "transcript-view"]
    videoId: Optional[str] = None
    query: Optional[str] = None
    title: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
