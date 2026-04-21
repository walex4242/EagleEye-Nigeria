"""
api/utils/security.py
─────────────────────
Data delay enforcement for anonymous users.
Imports JWT verification from your existing api/auth/security.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import Request

# ══════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════
ANONYMOUS_DELAY_MINUTES = 60
REALTIME_ROLES = frozenset({"superadmin", "admin", "military", "analyst"})


# ══════════════════════════════════════════
# USER EXTRACTION — uses YOUR existing auth
# ══════════════════════════════════════════
def get_user_from_request(request: Request) -> Optional[dict]:
    """
    Extract authenticated user from the Authorization header.
    Uses your existing api.auth.security.decode_token().
    Returns None for anonymous / invalid / expired tokens.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ", 1)[1]
        if not token or token in ("undefined", "null", ""):
            return None

        # ── Import YOUR existing decode_token ──
        from api.auth.security import decode_token

        payload = decode_token(token)
        if not payload:
            return None

        # Verify it's an access token (not refresh)
        if payload.get("type") != "access":
            return None

        return payload

    except Exception as e:
        print(f"[SECURITY] Token extraction failed: {e}")
        return None


# ══════════════════════════════════════════
# DELAY CALCULATION
# ══════════════════════════════════════════
def get_data_delay(request: Request) -> dict[str, Any]:
    """
    Determine data delay based on user authentication.

    Authorized roles (superadmin, admin, military, analyst)
    → REALTIME access, no delay.

    Anonymous / public role
    → 60-minute delay on all data.
    """
    user = get_user_from_request(request)

    if user and user.get("role") in REALTIME_ROLES:
        return {
            "delayed": False,
            "delay_minutes": 0,
            "cutoff_time": None,
            "user_role": user.get("role", "unknown"),
            "access_level": "REALTIME",
        }

    # Anonymous or public-role users get delayed data
    cutoff = datetime.utcnow() - timedelta(minutes=ANONYMOUS_DELAY_MINUTES)
    return {
        "delayed": True,
        "delay_minutes": ANONYMOUS_DELAY_MINUTES,
        "cutoff_time": cutoff,
        "user_role": user.get("role", "anonymous") if user else "anonymous",
        "access_level": "DELAYED",
    }


# ══════════════════════════════════════════
# FEATURE FILTERING BY TIME
# ══════════════════════════════════════════
def filter_features_by_delay(
    features: list[dict],
    cutoff_time: Optional[datetime],
) -> list[dict]:
    """
    Remove features newer than the cutoff time.
    Parses FIRMS timestamp fields in multiple formats.
    Features with unparseable times are INCLUDED (conservative).
    """
    if not cutoff_time or not features:
        return features

    filtered = []
    for f in features:
        props = f.get("properties", {})
        feature_time = _parse_feature_time(props)

        # Can't determine time → include (conservative — likely old)
        if feature_time is None:
            filtered.append(f)
            continue

        # Only include features OLDER than cutoff
        if feature_time <= cutoff_time:
            filtered.append(f)

    return filtered


def _parse_feature_time(props: dict) -> Optional[datetime]:
    """
    Try to parse a datetime from FIRMS feature properties.
    Handles multiple field formats for robustness.
    """
    # 1. ISO datetime field
    acq_datetime = props.get("acq_datetime")
    if acq_datetime:
        try:
            clean = str(acq_datetime).replace("Z", "").replace("+00:00", "")
            return datetime.fromisoformat(clean)
        except (ValueError, AttributeError):
            pass

    # 2. FIRMS native: acq_date + acq_time (e.g. "2024-01-15" + "1342")
    acq_date = props.get("acq_date", "")
    acq_time = props.get("acq_time", "")
    if acq_date and acq_time:
        try:
            time_str = str(acq_time).zfill(4)
            dt_str = f"{acq_date} {time_str[:2]}:{time_str[2:]}"
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            pass

    # 3. Date-only fallback (midnight)
    if acq_date:
        try:
            return datetime.strptime(str(acq_date), "%Y-%m-%d")
        except (ValueError, AttributeError):
            pass

    return None


# ══════════════════════════════════════════
# RESPONSE METADATA INJECTION
# ══════════════════════════════════════════
def add_security_metadata(
    response: dict[str, Any],
    delay_info: dict[str, Any],
    original_count: int = 0,
    filtered_count: int = 0,
) -> dict[str, Any]:
    """Inject security/delay metadata into any API response."""
    security: dict[str, Any] = {
        "access_level": delay_info["access_level"],
        "data_delayed": delay_info["delayed"],
        "delay_minutes": delay_info["delay_minutes"],
        "user_role": delay_info["user_role"],
    }

    if delay_info["delayed"]:
        security["delayed_until"] = delay_info["cutoff_time"].isoformat()
        security["notice"] = (
            f"Data delayed by {delay_info['delay_minutes']} minutes "
            f"for security purposes. Sign in with authorized credentials "
            f"for real-time access."
        )
        withheld = original_count - filtered_count
        if withheld > 0:
            security["features_withheld"] = withheld

    response["security"] = security
    return response