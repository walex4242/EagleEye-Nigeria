"""
anomaly_score.py
─────────────────
Scores each hotspot on a 0–100 threat priority scale.
"""

from __future__ import annotations


RED_ZONE_MULTIPLIER = {
    "Northwest Corridor": 1.4,
    "Northeast Corridor": 1.4,
    "North Central":      1.2,
    "Other":              1.0,
}

CONFIDENCE_BASE = {
    "H": 60,
    "N": 35,
    "L": 15,
}

NIGHT_HOURS = set(range(18, 24)) | set(range(0, 6))


def _frp_score(frp_str: str) -> float:
    try:
        frp = float(frp_str)
        return min(frp / 50.0, 1.0) * 20
    except (ValueError, TypeError):
        return 0.0


def _brightness_score(brightness: float) -> float:
    if brightness <= 300:
        return 0.0
    return min((brightness - 300) / 100.0, 1.0) * 10


def _time_score(acq_time_str: str) -> float:
    try:
        hour = int(acq_time_str[:2])
        return 10.0 if hour in NIGHT_HOURS else 0.0
    except (ValueError, TypeError):
        return 0.0


def score_hotspot(properties: dict) -> float:
    confidence = properties.get("confidence", "L").upper()
    base = CONFIDENCE_BASE.get(confidence, 15)

    frp_pts        = _frp_score(properties.get("frp", "0"))
    brightness_pts = _brightness_score(float(properties.get("brightness", 300)))
    time_pts       = _time_score(str(properties.get("acq_time", "1200")))

    raw_score = base + frp_pts + brightness_pts + time_pts

    zone = properties.get("red_zone", "Other")
    multiplier = RED_ZONE_MULTIPLIER.get(zone, 1.0)

    return round(min(raw_score * multiplier, 100.0), 1)


def score_hotspots(geojson: dict) -> dict:
    features = geojson.get("features", [])
    scored = []

    for feature in features:
        props = feature.get("properties", {})
        score = score_hotspot(props)

        if score >= 80:
            priority = "CRITICAL"
        elif score >= 60:
            priority = "HIGH"
        elif score >= 40:
            priority = "ELEVATED"
        else:
            priority = "MONITOR"

        enriched_props = {**props, "threat_score": score, "priority": priority}
        scored.append({**feature, "properties": enriched_props})

    scored.sort(key=lambda f: f["properties"]["threat_score"], reverse=True)

    critical = sum(1 for f in scored if f["properties"]["priority"] == "CRITICAL")
    high     = sum(1 for f in scored if f["properties"]["priority"] == "HIGH")

    return {
        **geojson,
        "features": scored,
        "metadata": {
            **geojson.get("metadata", {}),
            "scored": True,
            "critical_count": critical,
            "high_count": high,
            "top_score": scored[0]["properties"]["threat_score"] if scored else 0,
        },
    }