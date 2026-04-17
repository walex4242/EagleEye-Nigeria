"""
api/routes/alerts.py
────────────────────
Alert and movement tracking endpoints for military intelligence.
Provides actionable threat notifications for security forces.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["Intelligence Alerts"])

ALERTS_DIR = Path(__file__).parent.parent.parent / "data" / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/api/alerts")
async def get_active_alerts(
    priority: str | None = Query(
        None, description="Filter: critical, high, medium, low"
    ),
    state: str | None = Query(
        None, description="Filter by Nigerian state"
    ),
    zone: str | None = Query(
        None, description="Filter by monitoring zone"
    ),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """
    Get active threat alerts.
    
    These alerts are generated automatically when the movement
    tracker detects hotspot cluster migration patterns consistent
    with camp relocations or corridor movements.
    """
    alerts_file = ALERTS_DIR / "active_alerts.json"

    if not alerts_file.exists():
        return {
            "alerts": [],
            "count": 0,
            "as_of": datetime.utcnow().isoformat(),
        }

    try:
        with open(alerts_file) as f:
            alerts: list[dict[str, Any]] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "alerts": [],
            "count": 0,
            "as_of": datetime.utcnow().isoformat(),
        }

    # Filter expired alerts
    now = datetime.utcnow().isoformat()
    alerts = [
        a for a in alerts
        if a.get("expires", now) >= now
    ]

    # Apply filters
    if priority:
        alerts = [
            a for a in alerts
            if a.get("priority") == priority.lower()
        ]
    if state:
        alerts = [
            a for a in alerts
            if state.lower() in a.get("state", "").lower()
        ]
    if zone:
        alerts = [
            a for a in alerts
            if zone.lower() in a.get("zone", "").lower()
        ]

    # Sort by priority
    priority_order = {
        "critical": 0, "high": 1, "medium": 2, "low": 3,
    }
    alerts.sort(
        key=lambda a: priority_order.get(
            a.get("priority", "low"), 4
        )
    )

    return {
        "alerts": alerts[:limit],
        "count": len(alerts),
        "as_of": datetime.utcnow().isoformat(),
    }


@router.get("/api/alerts/summary")
async def get_alert_summary() -> dict[str, Any]:
    """
    Get a summary of current threat situation for briefing.
    
    Use this for a quick overview of the threat landscape
    before diving into individual alerts.
    """
    alerts_file = ALERTS_DIR / "active_alerts.json"

    if not alerts_file.exists():
        return {
            "total_active": 0,
            "by_priority": {},
            "by_zone": {},
            "by_state": {},
            "critical_alerts": [],
            "last_updated": datetime.utcnow().isoformat(),
        }

    try:
        with open(alerts_file) as f:
            alerts: list[dict[str, Any]] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "total_active": 0,
            "by_priority": {},
            "by_zone": {},
            "by_state": {},
            "critical_alerts": [],
            "last_updated": datetime.utcnow().isoformat(),
        }

    now = datetime.utcnow().isoformat()
    active = [a for a in alerts if a.get("expires", now) >= now]

    by_priority: dict[str, int] = {}
    by_zone: dict[str, int] = {}
    by_state: dict[str, int] = {}

    for alert in active:
        p = alert.get("priority", "unknown")
        z = alert.get("zone", "unknown")
        s = alert.get("state", "unknown")
        by_priority[p] = by_priority.get(p, 0) + 1
        by_zone[z] = by_zone.get(z, 0) + 1
        by_state[s] = by_state.get(s, 0) + 1

    critical_alerts = [
        a for a in active if a.get("priority") == "critical"
    ]

    return {
        "total_active": len(active),
        "by_priority": by_priority,
        "by_zone": by_zone,
        "by_state": by_state,
        "critical_alerts": critical_alerts,
        "last_updated": datetime.utcnow().isoformat(),
    }


@router.delete("/api/alerts/{alert_id}")
async def dismiss_alert(alert_id: str) -> dict[str, Any]:
    """
    Dismiss/acknowledge an alert.
    Marks it as notified so it won't appear as new.
    """
    alerts_file = ALERTS_DIR / "active_alerts.json"

    if not alerts_file.exists():
        raise HTTPException(status_code=404, detail="No alerts found")

    try:
        with open(alerts_file) as f:
            alerts: list[dict[str, Any]] = json.load(f)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Error reading alerts")

    found = False
    for alert in alerts:
        if alert.get("alert_id") == alert_id:
            alert["notified"] = True
            alert["acknowledged_at"] = datetime.utcnow().isoformat()
            found = True
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Alert {alert_id} not found",
        )

    with open(alerts_file, "w") as f:
        json.dump(alerts, f, indent=2)

    return {
        "status": "acknowledged",
        "alert_id": alert_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/api/alerts/clear-expired")
async def clear_expired_alerts() -> dict[str, Any]:
    """Remove all expired alerts from storage."""
    alerts_file = ALERTS_DIR / "active_alerts.json"

    if not alerts_file.exists():
        return {"removed": 0, "remaining": 0}

    try:
        with open(alerts_file) as f:
            alerts: list[dict[str, Any]] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"removed": 0, "remaining": 0}

    now = datetime.utcnow().isoformat()
    before_count = len(alerts)

    active = [a for a in alerts if a.get("expires", now) >= now]

    with open(alerts_file, "w") as f:
        json.dump(active, f, indent=2)

    removed = before_count - len(active)

    return {
        "removed": removed,
        "remaining": len(active),
        "timestamp": datetime.utcnow().isoformat(),
    }