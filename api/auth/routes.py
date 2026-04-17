"""
api/auth/routes.py
──────────────────
Authentication and user management endpoints.
All IDs are PostgreSQL native UUIDs.
"""

import os
import uuid as uuid_module
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from api.database.engine import get_db
from api.database.models import User, UserRole, AuditLog
from api.auth.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from api.auth.schemas import (
    LoginRequest, TokenResponse, RefreshRequest,
    RegisterRequest, UserPublic, UserUpdate, RoleUpdate,
    ChangePasswordRequest,
)
from api.auth.dependencies import (
    require_auth, require_admin, require_military,
    optional_auth, log_access,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

ALLOW_PUBLIC_REGISTRATION = os.getenv(
    "ALLOW_PUBLIC_REGISTRATION", "false",
).lower() == "true"


# ── Helper: parse UUID from path/query ────────────────────────

def _parse_uuid(user_id: str) -> uuid_module.UUID:
    """Convert string to UUID, raise 400 if invalid."""
    try:
        return uuid_module.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: {user_id}",
        )


# ── Login ─────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate and receive JWT tokens."""
    user = db.query(User).filter(
        (User.email == body.email) | (User.username == body.email)
    ).first()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated — contact administrator",
        )

    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()

    # Create tokens — UUID is auto-converted to string in security.py
    token_data = {"sub": user.id, "role": user.role}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    log_access("login", user, request, db)
    print(f"[AUTH] ✓ Login: {user.username} ({user.role})")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserPublic.from_db(user),
    )


# ── Refresh Token ─────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Get a new access token using a refresh token."""
    payload = decode_token(body.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_uuid = _parse_uuid(payload.get("sub", ""))
    user = db.query(User).filter(User.id == user_uuid).first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    token_data = {"sub": user.id, "role": user.role}
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserPublic.from_db(user),
    )


# ── Register (Admin-controlled) ──────────────────────────────

@router.post("/register", response_model=UserPublic)
async def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: Optional[User] = Depends(optional_auth),
):
    """
    Register a new user.
    - Public registration creates 'public' role (if enabled).
    - Admin can create users with any role.
    """
    is_admin = admin and admin.role in [UserRole.SUPERADMIN, UserRole.ADMIN]

    if not is_admin and not ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is restricted. Contact administrator.",
        )

    # Check duplicates
    existing = db.query(User).filter(
        (User.email == body.email) | (User.username == body.username)
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    # Determine role
    role = UserRole.PUBLIC
    if is_admin and hasattr(body, "role"):
        role = getattr(body, "role", UserRole.PUBLIC)

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=role,
        rank=body.rank,
        unit=body.unit,
        service_id=body.service_id,
        phone=body.phone,
        is_verified=bool(is_admin),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    if is_admin:
        log_access("admin_create_user", admin, request, db, {
            "new_user": user.username,
            "role": role,
        })

    print(f"[AUTH] ✓ New user registered: {user.username} ({user.role})")
    return UserPublic.from_db(user)


# ── Current User Profile ─────────────────────────────────────

@router.get("/me", response_model=UserPublic)
async def get_profile(user: User = Depends(require_auth)):
    """Get current user profile."""
    return UserPublic.from_db(user)


@router.put("/me", response_model=UserPublic)
async def update_profile(
    body: UserUpdate,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Update current user profile."""
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.rank is not None:
        user.rank = body.rank
    if body.unit is not None:
        user.unit = body.unit
    if body.phone is not None:
        user.phone = body.phone

    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return UserPublic.from_db(user)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Change password for current user."""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    user.hashed_password = hash_password(body.new_password)
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Password updated successfully"}


# ── Admin: User Management ────────────────────────────────────

@router.get("/users", response_model=List[UserPublic])
async def list_users(
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users (admin only)."""
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    query = query.order_by(User.created_at.desc())
    return [UserPublic.from_db(u) for u in query.all()]


@router.put("/users/{user_id}/role", response_model=UserPublic)
async def update_user_role(
    user_id: str,
    body: RoleUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a user's role (admin only)."""
    if body.role not in UserRole.ALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {UserRole.ALL}",
        )

    target_uuid = _parse_uuid(user_id)
    target = db.query(User).filter(User.id == target_uuid).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent demoting superadmin by non-superadmin
    if (
        target.role == UserRole.SUPERADMIN
        and admin.role != UserRole.SUPERADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify superadmin",
        )

    old_role = target.role
    target.role = body.role
    target.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(target)

    log_access("change_role", admin, request, db, {
        "target_user": target.username,
        "old_role": old_role,
        "new_role": body.role,
    })

    print(f"[AUTH] Role changed: {target.username} {old_role} → {body.role}")
    return UserPublic.from_db(target)


@router.put("/users/{user_id}/verify")
async def verify_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Verify/activate a user account (admin only)."""
    target_uuid = _parse_uuid(user_id)
    target = db.query(User).filter(User.id == target_uuid).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.is_verified = True
    target.is_active = True
    target.updated_at = datetime.utcnow()
    db.commit()

    log_access("verify_user", admin, request, db, {
        "target_user": target.username,
    })

    print(f"[AUTH] ✓ User verified: {target.username}")
    return {"message": f"User {target.username} verified and activated"}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deactivate a user account (admin only). Does not delete data."""
    target_uuid = _parse_uuid(user_id)
    target = db.query(User).filter(User.id == target_uuid).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target.role == UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot deactivate superadmin",
        )

    target.is_active = False
    target.updated_at = datetime.utcnow()
    db.commit()

    log_access("deactivate_user", admin, request, db, {
        "target_user": target.username,
    })

    print(f"[AUTH] ✗ User deactivated: {target.username}")
    return {"message": f"User {target.username} deactivated"}


# ── Admin: Audit Log ──────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(
    limit: int = 100,
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """View audit log (admin only)."""
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        uid = _parse_uuid(user_id)
        query = query.filter(AuditLog.user_id == uid)

    logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()

    return {
        "count": len(logs),
        "logs": [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "resource": log.resource,
                "ip_address": log.ip_address,
                "details": log.details,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ],
    }