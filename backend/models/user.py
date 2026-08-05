"""
User models - Pydantic schemas
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    # Single optional display name — split into firstName/lastName server-side.
    name: Optional[str] = Field(default="", max_length=100)
    # Legacy identity fields — now optional and auto-filled by the auth service
    # (username is generated from the email) so signup only needs email+password+name.
    firstName: Optional[str] = Field(default=None, max_length=50)
    lastName: Optional[str] = Field(default=None, max_length=50)
    username: Optional[str] = Field(default=None, min_length=3, max_length=30)
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
    type: Literal["watch", "search", "transcript-view", "merge"]
    videoId: Optional[str] = None
    query: Optional[str] = None
    title: Optional[str] = None
    jobId: Optional[str] = None          # for merge type — links back to the result page
    videoCount: Optional[int] = None     # for merge type — how many videos were merged
    timestamp: datetime = Field(default_factory=datetime.utcnow)
