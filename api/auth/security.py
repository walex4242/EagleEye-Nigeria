"""
api/auth/security.py
────────────────────
JWT token creation/verification and password hashing.
Handles PostgreSQL UUID ↔ string conversion for JWT payloads.
Uses bcrypt directly (no passlib dependency).
"""

import os
import uuid as uuid_module
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import bcrypt
from jose import JWTError, jwt

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Configuration ─────────────────────────────────────────────

JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "CHANGE-THIS-IN-PRODUCTION-min-32-characters-long",
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480"),
)
REFRESH_TOKEN_EXPIRE_DAYS = int(
    os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30"),
)

# ── Password Hashing ─────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (truncated to 72 bytes)."""
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        pw_bytes = plain_password.encode("utf-8")[:72]
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pw_bytes, hashed_bytes)
    except (ValueError, TypeError) as e:
        print(f"[AUTH] Password verification error: {e}")
        return False


# ── JWT Tokens ────────────────────────────────────────────────

def _serialize_value(val: Any) -> Any:
    """Convert non-serializable types (UUID, datetime) to strings."""
    if isinstance(val, uuid_module.UUID):
        return str(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = {k: _serialize_value(v) for k, v in data.items()}
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": now,
    })
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = {k: _serialize_value(v) for k, v in data.items()}
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": now,
    })
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(
            token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM],
        )
        return payload
    except JWTError as e:
        print(f"[AUTH] Token decode failed: {e}")
        return None