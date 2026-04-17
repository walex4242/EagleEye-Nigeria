"""
api/auth/dependencies.py
────────────────────────
FastAPI dependencies for authentication and authorization.
All UUID handling is PostgreSQL-native (UUID column type).
"""

import uuid as uuid_module
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime

from api.database.engine import get_db
from api.database.models import User, AuditLog, UserRole
from api.auth.security import decode_token

security_scheme = HTTPBearer(auto_error=False)


# ── User Extraction ───────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        security_scheme,
    ),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Extract and validate current user from JWT token.
    Converts JWT string sub → PostgreSQL UUID for query.
    Returns None for unauthenticated requests.
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — use access token",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload — missing sub",
        )

    # Convert JWT string back to PostgreSQL UUID
    try:
        user_uuid = uuid_module.UUID(user_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier format",
        )

    user = db.query(User).filter(User.id == user_uuid).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated — contact administrator",
        )

    return user


# ── Role-Based Access Control ─────────────────────────────────

def require_auth(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Require any authenticated user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed_roles: str):
    """
    Factory — returns a dependency requiring specific roles.

    Usage:
        @router.get(
            "/secret",
            dependencies=[Depends(require_role("military", "admin"))]
        )
    """
    def _checker(user: User = Depends(require_auth)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. "
                    f"Required: {', '.join(allowed_roles)}"
                ),
            )
        return user
    return _checker


def require_military(
    user: User = Depends(require_auth),
) -> User:
    """Shortcut: require military-level access."""
    if user.role not in UserRole.MILITARY_ONLY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Military clearance required",
        )
    return user


def require_analyst(
    user: User = Depends(require_auth),
) -> User:
    """Shortcut: require analyst-level access or higher."""
    if user.role not in UserRole.PRIVILEGED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst clearance required",
        )
    return user


def require_admin(
    user: User = Depends(require_auth),
) -> User:
    """Shortcut: require admin access."""
    if user.role not in [UserRole.SUPERADMIN, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user


def optional_auth(
    user: Optional[User] = Depends(get_current_user),
) -> Optional[User]:
    """Returns user if authenticated, None otherwise."""
    return user


# ── Audit Logging ─────────────────────────────────────────────

def log_access(
    action: str,
    user: Optional[User],
    request: Request,
    db: Session,
    details: Optional[dict] = None,
):
    """Record an access event in the audit log (PostgreSQL)."""
    try:
        audit = AuditLog(
            user_id=user.id if user else None,
            action=action,
            resource=str(request.url.path),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500],
            details=details,
        )
        db.add(audit)
        db.commit()
    except Exception as e:
        print(f"[AUDIT] ⚠ Failed to log access: {e}")
        # Don't crash the request if audit logging fails
        try:
            db.rollback()
        except Exception:
            pass