"""
api/auth/schemas.py
───────────────────
Pydantic models for auth endpoints.
Uses str for UUID fields (Pydantic serializes UUID from PostgreSQL).
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    email: str = Field(..., description="Official email address")
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    rank: Optional[str] = None
    unit: Optional[str] = None
    service_id: Optional[str] = None
    phone: Optional[str] = None


class UserPublic(BaseModel):
    id: str  # UUID comes as string from PostgreSQL via Pydantic
    email: str
    username: str
    full_name: str
    role: str
    rank: Optional[str] = None
    unit: Optional[str] = None
    is_active: bool
    is_verified: bool
    last_login: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_db(cls, user):
        """
        Create UserPublic from a SQLAlchemy User model.
        Handles UUID → str conversion explicitly.
        """
        return cls(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            rank=user.rank,
            unit=user.unit,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
        )


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    rank: Optional[str] = None
    unit: Optional[str] = None
    phone: Optional[str] = None


class RoleUpdate(BaseModel):
    role: str = Field(..., description="New role to assign")


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)