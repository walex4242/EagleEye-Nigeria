"""
api/database/persistence.py
───────────────────────────
Handles saving API data to PostgreSQL and managing
the time-delayed public release system.
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from api.database.models import (
    HotspotRecord, VegetationEvent, MovementRecord,
    SavedAlert, DataSnapshot, DataClassification,
)

# Hours before restricted data becomes public
PUBLIC_DELAY_HOURS = int(os.getenv("PUBLIC_DATA_DELAY_HOURS", "72"))


# ── Hotspot Persistence ──────────────────────────────────────

def save_hotspots(
    db: Session,
    geojson: Dict,
    classification: str = DataClassification.RESTRICTED,
) -> int:
    """
    Save hotspot features to PostgreSQL.
    Returns count of new records saved (skips duplicates).
    """
    features = geojson.get("features", [])
    if not features:
        return 0

    release_at = datetime.utcnow() + timedelta(hours=PUBLIC_DELAY_HOURS)
    saved = 0

    for f in features:
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        lon = float(coords[0]) if len(coords) > 0 else 0.0
        lat = float(coords[1]) if len(coords) > 1 else 0.0

        # Skip if duplicate (same coords + date + time)
        existing = db.query(HotspotRecord).filter(
            and_(
                HotspotRecord.latitude == round(lat, 4),
                HotspotRecord.longitude == round(lon, 4),
                HotspotRecord.acq_date == props.get("acq_date", ""),
                HotspotRecord.acq_time == props.get("acq_time", ""),
            )
        ).first()

        if existing:
            continue

        location = props.get("location", {})

        record = HotspotRecord(
            latitude=lat,
            longitude=lon,
            brightness=_safe_float(props.get("brightness")),
            confidence=str(props.get("confidence", "")).upper(),
            frp=_safe_float(props.get("frp")),
            acq_date=props.get("acq_date", ""),
            acq_time=props.get("acq_time", ""),
            satellite=props.get("satellite", ""),
            daynight=props.get("daynight", ""),
            threat_score=_safe_float(props.get("threat_score")),
            priority=props.get("priority", ""),
            threat_tier=props.get("threat_tier", ""),
            state=props.get("state", "") or location.get("state", ""),
            lga=props.get("lga", "") or location.get("lga", ""),
            nearest_town=props.get("nearest_town", "") or location.get("nearest_town", ""),
            red_zone=props.get("red_zone", ""),
            geo_zone=location.get("geo_zone", ""),
            location_data=location if location else None,
            classification=classification,
            public_release_at=release_at,
        )

        db.add(record)
        saved += 1

    if saved > 0:
        db.commit()
        print(f"[DB] ✓ Saved {saved} new hotspot records (release at {release_at})")

    return saved


# ── Vegetation Event Persistence ──────────────────────────────

def save_vegetation_events(
    db: Session,
    events: List[Dict],
    classification: str = DataClassification.CONFIDENTIAL,
) -> int:
    """Save vegetation change events to PostgreSQL."""
    if not events:
        return 0

    release_at = datetime.utcnow() + timedelta(hours=PUBLIC_DELAY_HOURS)
    saved = 0

    for evt in events:
        # Skip duplicates
        existing = db.query(VegetationEvent).filter(
            VegetationEvent.event_id == evt.get("event_id", ""),
        ).first()

        if existing:
            continue

        location = evt.get("location", {})

        record = VegetationEvent(
            event_id=evt.get("event_id", ""),
            latitude=evt.get("latitude", 0),
            longitude=evt.get("longitude", 0),
            bbox=evt.get("bbox"),
            date_before=evt.get("date_before", ""),
            date_after=evt.get("date_after", ""),
            index_used=evt.get("index_used", ""),
            mean_change=evt.get("mean_change", 0),
            max_change=evt.get("max_change", 0),
            area_hectares=evt.get("area_hectares", 0),
            area_pixels=evt.get("area_pixels", 0),
            severity=evt.get("severity", ""),
            event_classification=evt.get("classification", ""),
            confidence=evt.get("confidence", 0),
            vegetation_zone=evt.get("vegetation_zone", ""),
            state=evt.get("state", "") or location.get("state", ""),
            lga=evt.get("lga", "") or location.get("lga", ""),
            nearest_town=evt.get("nearest_town", "") or location.get("nearest_town", ""),
            location_data=location if location else None,
            nearby_hotspots=evt.get("nearby_hotspots", 0),
            nearby_conflicts=evt.get("nearby_conflicts", 0),
            correlation_data=evt.get("correlation_data"),
            classification=classification,
            public_release_at=release_at,
        )

        db.add(record)
        saved += 1

    if saved > 0:
        db.commit()
        print(f"[DB] ✓ Saved {saved} vegetation events")

    return saved


# ── Public Data Query ─────────────────────────────────────────

def get_public_hotspots(
    db: Session,
    days: int = 7,
    state: Optional[str] = None,
    limit: int = 500,
) -> List[Dict]:
    """
    Get hotspot records that have passed the public release delay.
    Only returns records where public_release_at < now.
    """
    now = datetime.utcnow()

    query = db.query(HotspotRecord).filter(
        and_(
            HotspotRecord.public_release_at <= now,
            HotspotRecord.classification.in_([
                DataClassification.RESTRICTED,
                DataClassification.UNCLASSIFIED,
            ]),
        )
    )

    if state:
        query = query.filter(HotspotRecord.state == state)

    if days:
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        query = query.filter(HotspotRecord.acq_date >= cutoff)

    records = query.order_by(
        HotspotRecord.acq_date.desc(),
        HotspotRecord.threat_score.desc(),
    ).limit(limit).all()

    return [_hotspot_to_feature(r) for r in records]


def get_public_vegetation_events(
    db: Session,
    days: int = 30,
    limit: int = 200,
) -> List[Dict]:
    """Get vegetation events that have passed the public release delay."""
    now = datetime.utcnow()

    query = db.query(VegetationEvent).filter(
        and_(
            VegetationEvent.public_release_at <= now,
            VegetationEvent.classification.in_([
                DataClassification.RESTRICTED,
                DataClassification.CONFIDENTIAL,
                DataClassification.UNCLASSIFIED,
            ]),
        )
    )

    records = query.order_by(
        VegetationEvent.date_after.desc(),
    ).limit(limit).all()

    return [_veg_event_to_dict(r) for r in records]


# ── Military Data Query (full access) ────────────────────────

def get_military_hotspots(
    db: Session,
    days: int = 1,
    state: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 1000,
) -> List[Dict]:
    """
    Get ALL hotspot records (no delay, no classification filter).
    Requires military clearance.
    """
    query = db.query(HotspotRecord)

    if state:
        query = query.filter(HotspotRecord.state == state)

    if priority:
        query = query.filter(HotspotRecord.priority == priority)

    if days:
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        query = query.filter(HotspotRecord.acq_date >= cutoff)

    records = query.order_by(
        HotspotRecord.threat_score.desc(),
    ).limit(limit).all()

    return [_hotspot_to_feature(r) for r in records]


# ── Snapshot Storage ──────────────────────────────────────────

def save_snapshot(
    db: Session,
    snapshot_type: str,
    data: Dict,
    feature_count: int = 0,
) -> None:
    """Save a periodic data snapshot for historical tracking."""
    now = datetime.utcnow()
    release_at = now + timedelta(hours=PUBLIC_DELAY_HOURS)

    # Check for existing snapshot of same type today
    existing = db.query(DataSnapshot).filter(
        and_(
            DataSnapshot.snapshot_type == snapshot_type,
            DataSnapshot.snapshot_date >= now.replace(
                hour=0, minute=0, second=0,
            ),
        )
    ).first()

    if existing:
        existing.data = data
        existing.feature_count = feature_count
        existing.metadata = {"updated_at": now.isoformat()}
    else:
        snapshot = DataSnapshot(
            snapshot_type=snapshot_type,
            snapshot_date=now,
            data=data,
            feature_count=feature_count,
            classification=DataClassification.RESTRICTED,
            public_release_at=release_at,
        )
        db.add(snapshot)

    db.commit()


# ── Helpers ───────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _hotspot_to_feature(record: HotspotRecord) -> Dict:
    """Convert a HotspotRecord to GeoJSON feature."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [record.longitude, record.latitude],
        },
        "properties": {
            "brightness": record.brightness,
            "confidence": record.confidence,
            "frp": str(record.frp) if record.frp else "0",
            "acq_date": record.acq_date,
            "acq_time": record.acq_time,
            "satellite": record.satellite,
            "daynight": record.daynight,
            "threat_score": record.threat_score,
            "priority": record.priority,
            "threat_tier": record.threat_tier,
            "state": record.state,
            "lga": record.lga,
            "nearest_town": record.nearest_town,
            "red_zone": record.red_zone,
            "location": record.location_data or {},
            "google_maps_url": (
                f"https://www.google.com/maps/search/?api=1"
                f"&query={record.latitude},{record.longitude}"
            ),
        },
    }


def _veg_event_to_dict(record: VegetationEvent) -> Dict:
    """Convert a VegetationEvent to dict."""
    return {
        "event_id": record.event_id,
        "latitude": record.latitude,
        "longitude": record.longitude,
        "date_before": record.date_before,
        "date_after": record.date_after,
        "index_used": record.index_used,
        "mean_change": record.mean_change,
        "max_change": record.max_change,
        "area_hectares": record.area_hectares,
        "area_pixels": record.area_pixels,
        "severity": record.severity,
        "classification": record.event_classification,
        "confidence": record.confidence,
        "vegetation_zone": record.vegetation_zone,
        "state": record.state,
        "lga": record.lga,
        "nearest_town": record.nearest_town,
        "location": record.location_data or {},
    }