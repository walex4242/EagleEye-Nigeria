"""
api/utils/data_delay.py
───────────────────────
60-minute data delay enforcement for anonymous/public users.
Uses the existing api.auth.security.decode_token() for JWT verification.

Security tiers:
  REALTIME  → superadmin, admin, military, analyst
  DELAYED   → public role, anonymous (no token)
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
# USER EXTRACTION — wraps YOUR existing JWT
# ══════════════════════════════════════════
def _get_user_from_request(request: Request) -> Optional[dict]:
    """
    Extract the authenticated user payload from the Authorization header.
    Returns None for anonymous / invalid / expired tokens.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ", 1)[1]
        if not token or token in ("undefined", "null", ""):
            return None

        # ── YOUR existing decode_token from api/auth/security.py ──
        from api.auth.security import decode_token

        payload = decode_token(token)
        if not payload:
            return None

        # Only accept access tokens (not refresh)
        if payload.get("type") != "access":
            return None

        return payload

    except Exception as e:
        print(f"[DATA_DELAY] Token extraction failed: {e}")
        return None


# ══════════════════════════════════════════
# DELAY CALCULATION
# ══════════════════════════════════════════
def get_data_delay(request: Request) -> dict[str, Any]:
    """
    Determine whether this request gets real-time or delayed data.

    Returns:
        {
            "delayed": bool,
            "delay_minutes": int,
            "cutoff_time": datetime | None,
            "user_role": str,
            "access_level": "REALTIME" | "DELAYED",
        }
    """
    user = _get_user_from_request(request)

    # Authorized role → real-time
    if user and user.get("role") in REALTIME_ROLES:
        return {
            "delayed": False,
            "delay_minutes": 0,
            "cutoff_time": None,
            "user_role": user.get("role", "unknown"),
            "access_level": "REALTIME",
        }

    # Anonymous or public role → delayed
    cutoff = datetime.utcnow() - timedelta(minutes=ANONYMOUS_DELAY_MINUTES)
    return {
        "delayed": True,
        "delay_minutes": ANONYMOUS_DELAY_MINUTES,
        "cutoff_time": cutoff,
        "user_role": user.get("role", "anonymous") if user else "anonymous",
        "access_level": "DELAYED",
    }


# ══════════════════════════════════════════
# FEATURE TIME PARSING
# ══════════════════════════════════════════
def _parse_feature_time(props: dict) -> Optional[datetime]:
    """
    Parse acquisition datetime from FIRMS feature properties.
    Tries multiple field formats for robustness.
    """
    # 1. ISO datetime (e.g. "2024-06-15T13:42:00Z")
    acq_datetime = props.get("acq_datetime")
    if acq_datetime:
        try:
            clean = str(acq_datetime).replace("Z", "").replace("+00:00", "")
            return datetime.fromisoformat(clean)
        except (ValueError, AttributeError):
            pass

    # 2. FIRMS native: acq_date="2024-06-15" + acq_time="1342"
    acq_date = props.get("acq_date", "")
    acq_time = props.get("acq_time", "")
    if acq_date and acq_time:
        try:
            time_str = str(acq_time).zfill(4)
            dt_str = f"{acq_date} {time_str[:2]}:{time_str[2:]}"
            return datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            pass

    # 3. Date-only fallback (treated as midnight)
    if acq_date:
        try:
            return datetime.strptime(str(acq_date), "%Y-%m-%d")
        except (ValueError, AttributeError):
            pass

    return None


# ══════════════════════════════════════════
# FEATURE FILTERING
# ══════════════════════════════════════════
def filter_features_by_delay(
    features: list[dict],
    cutoff_time: Optional[datetime],
) -> list[dict]:
    """
    Remove features newer than the cutoff time.
    Features with unparseable timestamps are INCLUDED (conservative approach).
    """
    if not cutoff_time or not features:
        return features

    filtered = []
    for f in features:
        props = f.get("properties", {})
        feature_time = _parse_feature_time(props)

        # Can't parse time → include (conservative — likely older data)
        if feature_time is None:
            filtered.append(f)
            continue

        # Only include features OLDER than cutoff
        if feature_time <= cutoff_time:
            filtered.append(f)

    return filtered


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