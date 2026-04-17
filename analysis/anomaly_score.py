"""
anomaly_score.py
─────────────────
Scores each hotspot on a 0–100 threat priority scale.

Scoring factors:
  - Confidence level (base score)
  - Fire Radiative Power (FRP) — intensity
  - Brightness temperature — thermal signature
  - Time of day — nighttime fires are more suspicious
  - Red zone location — conflict corridor multiplier
  - State threat history — known high-risk states
  - Proximity clustering — multiple nearby hotspots increase threat
  - Vegetation context — fires near forest/clearing areas
"""

from __future__ import annotations
from math import radians, cos, sin, asin, sqrt
from typing import Dict, List, Optional, Tuple


# ── Zone Multipliers ──────────────────────────────────────────

RED_ZONE_MULTIPLIER: Dict[str, float] = {
    "Northwest Corridor": 1.4,
    "Northeast Corridor": 1.4,
    "North Central":      1.2,
    "Other":              1.0,
}

# States with known active security threats (weighted by severity)
# Sources: ACLED, NST, ISWAP/Boko Haram activity reports
STATE_THREAT_MULTIPLIER: Dict[str, float] = {
    # Northeast — Boko Haram / ISWAP
    "Borno":    1.5,
    "Yobe":     1.4,
    "Adamawa":  1.3,
    "Gombe":    1.1,
    "Bauchi":   1.1,

    # Northwest — Banditry
    "Zamfara":  1.5,
    "Katsina":  1.4,
    "Kaduna":   1.3,
    "Sokoto":   1.3,
    "Kebbi":    1.2,
    "Niger":    1.2,

    # North Central — Herder-farmer conflict
    "Benue":    1.3,
    "Plateau":  1.3,
    "Nasarawa": 1.2,
    "Taraba":   1.2,
    "Kogi":     1.1,

    # Niger Delta — Militancy / oil theft
    "Rivers":     1.2,
    "Bayelsa":    1.2,
    "Delta":      1.2,
    "Akwa Ibom":  1.1,

    # Southeast — ESN/IPOB
    "Imo":      1.2,
    "Anambra":  1.2,
    "Ebonyi":   1.1,
}

# ── Confidence Base Scores ────────────────────────────────────

CONFIDENCE_BASE: Dict[str, int] = {
    "H": 55,
    "N": 30,
    "L": 12,
}

# ── Time-of-Day Scoring ──────────────────────────────────────

NIGHT_HOURS = set(range(20, 24)) | set(range(0, 5))   # 8pm - 5am (most suspicious)
DUSK_DAWN_HOURS = {5, 6, 18, 19}                       # Transitional hours


# ── Haversine ─────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * asin(sqrt(a))


# ── Individual Scoring Components ─────────────────────────────

def _frp_score(frp_str: str) -> float:
    """
    Fire Radiative Power score (0–20).
    FRP > 50 MW is very intense for Nigeria's vegetation types.
    """
    try:
        frp = float(frp_str)
        if frp <= 0:
            return 0.0
        if frp >= 100:
            return 20.0
        return min(frp / 50.0, 1.0) * 20
    except (ValueError, TypeError):
        return 0.0


def _brightness_score(brightness: float) -> float:
    """
    Brightness temperature score (0–15).
    VIIRS bright_ti4 typical range: 290–500K.
    >350K is significant, >400K is very intense.
    """
    if brightness <= 300:
        return 0.0
    if brightness >= 450:
        return 15.0
    return min((brightness - 300) / 150.0, 1.0) * 15


def _time_score(acq_time_str: str) -> float:
    """
    Time-of-day score (0–12).
    Nighttime fires are more suspicious (less likely agricultural).
    Deep night (8pm-5am) scores highest.
    """
    try:
        hour = int(str(acq_time_str)[:2])
        if hour in NIGHT_HOURS:
            return 12.0
        if hour in DUSK_DAWN_HOURS:
            return 6.0
        return 0.0
    except (ValueError, TypeError, IndexError):
        return 0.0


def _state_score(state: str) -> float:
    """
    State-level threat context bonus (0–8).
    Known conflict states get additional points.
    """
    if not state or state == '—' or state == 'Unknown':
        return 0.0
    multiplier = STATE_THREAT_MULTIPLIER.get(state, 1.0)
    # Convert multiplier to 0-8 point scale
    return min((multiplier - 1.0) * 16.0, 8.0)


def _proximity_score(
    lat: float,
    lon: float,
    all_coords: List[Tuple[float, float]],
    radius_km: float = 5.0,
) -> float:
    """
    Clustering/proximity score (0–10).
    Multiple hotspots within radius_km suggests a larger event.
    """
    if not all_coords:
        return 0.0

    nearby = 0
    for other_lat, other_lon in all_coords:
        if other_lat == lat and other_lon == lon:
            continue
        dist = _haversine(lat, lon, other_lat, other_lon)
        if dist <= radius_km:
            nearby += 1

    if nearby >= 10:
        return 10.0
    if nearby >= 5:
        return 7.0
    if nearby >= 3:
        return 5.0
    if nearby >= 1:
        return 3.0
    return 0.0


# ── Priority Classification ──────────────────────────────────

def _classify_priority(score: float) -> str:
    """Classify threat level from score."""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "ELEVATED"
    return "MONITOR"


def _classify_tier(score: float, state: str) -> str:
    """
    Military response tier classification.
    Combines score with state-level threat context.
    """
    state_mult = STATE_THREAT_MULTIPLIER.get(state, 1.0)

    if score >= 80 and state_mult >= 1.3:
        return "Tier 1 — Immediate Response"
    if score >= 70 or (score >= 60 and state_mult >= 1.3):
        return "Tier 2 — Rapid Assessment"
    if score >= 50 or (score >= 40 and state_mult >= 1.2):
        return "Tier 3 — Scheduled Investigation"
    return "Tier 4 — Monitoring Only"


# ── Single Hotspot Scoring ────────────────────────────────────

def score_hotspot(
    properties: Dict,
    all_coords: Optional[List[Tuple[float, float]]] = None,
) -> Dict:
    """
    Score a single hotspot and return scoring breakdown.

    Args:
        properties: Feature properties dict
        all_coords: Optional list of all (lat, lon) for proximity scoring

    Returns:
        Dict with score, priority, tier, and breakdown
    """
    confidence = str(properties.get("confidence", "L")).strip().upper()
    base = CONFIDENCE_BASE.get(confidence, 12)

    frp_pts = _frp_score(properties.get("frp", "0"))

    brightness_raw = properties.get("brightness", 300)
    try:
        brightness_val = float(brightness_raw)
    except (ValueError, TypeError):
        brightness_val = 300.0
    brightness_pts = _brightness_score(brightness_val)

    time_pts = _time_score(str(properties.get("acq_time", "1200")))

    # State from location enrichment or properties
    state = (
        properties.get("state", "")
        or (properties.get("location", {}) or {}).get("state", "")
        or ""
    )
    state_pts = _state_score(state)

    # Proximity scoring
    prox_pts = 0.0
    if all_coords:
        coords = properties.get("_coords", (0, 0))
        prox_pts = _proximity_score(
            coords[0], coords[1], all_coords,
        )

    # Raw score (max possible ~ 55 + 20 + 15 + 12 + 8 + 10 = 120 before multiplier)
    raw_score = base + frp_pts + brightness_pts + time_pts + state_pts + prox_pts

    # Zone multiplier
    zone = properties.get("red_zone", "Other")
    zone_mult = RED_ZONE_MULTIPLIER.get(zone, 1.0)

    # Final score (capped at 100)
    final_score = round(min(raw_score * zone_mult, 100.0), 1)

    priority = _classify_priority(final_score)
    tier = _classify_tier(final_score, state)

    return {
        "threat_score": final_score,
        "priority": priority,
        "threat_tier": tier,
        "scoring_breakdown": {
            "confidence_base": base,
            "frp_pts": round(frp_pts, 1),
            "brightness_pts": round(brightness_pts, 1),
            "time_pts": round(time_pts, 1),
            "state_pts": round(state_pts, 1),
            "proximity_pts": round(prox_pts, 1),
            "zone_multiplier": zone_mult,
            "raw_score": round(raw_score, 1),
        },
    }


# ── Batch Scoring ─────────────────────────────────────────────

def score_hotspots(geojson: Dict) -> Dict:
    """
    Score all hotspots in a GeoJSON FeatureCollection.

    Performs two passes:
      1. Collect all coordinates for proximity analysis
      2. Score each hotspot with full context

    Returns enriched GeoJSON with scores, priorities, and tiers.
    """
    features = geojson.get("features", [])
    if not features:
        return {
            **geojson,
            "metadata": {
                **geojson.get("metadata", {}),
                "scored": True,
                "critical_count": 0,
                "high_count": 0,
                "elevated_count": 0,
                "monitor_count": 0,
                "top_score": 0,
                "mean_score": 0,
            },
        }

    # Pass 1: collect coordinates for proximity scoring
    all_coords: List[Tuple[float, float]] = []
    for f in features:
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        lon = float(coords[0]) if len(coords) > 0 else 0.0
        lat = float(coords[1]) if len(coords) > 1 else 0.0
        all_coords.append((lat, lon))

    # Pass 2: score each hotspot
    scored: List[Dict] = []

    for i, feature in enumerate(features):
        props = feature.get("properties", {})

        # Inject coords for proximity scoring
        props["_coords"] = all_coords[i]

        result = score_hotspot(props, all_coords)

        # Build enriched properties
        enriched_props = {
            **props,
            "threat_score": result["threat_score"],
            "priority": result["priority"],
            "threat_tier": result["threat_tier"],
        }

        # Remove internal helper
        enriched_props.pop("_coords", None)

        scored.append({**feature, "properties": enriched_props})

    # Sort by threat score (highest first)
    scored.sort(key=lambda f: f["properties"]["threat_score"], reverse=True)

    # Compute summary statistics
    scores = [f["properties"]["threat_score"] for f in scored]
    priorities = [f["properties"]["priority"] for f in scored]

    critical_count = priorities.count("CRITICAL")
    high_count = priorities.count("HIGH")
    elevated_count = priorities.count("ELEVATED")
    monitor_count = priorities.count("MONITOR")

    top_score = scores[0] if scores else 0
    mean_score = round(sum(scores) / len(scores), 1) if scores else 0

    # Top 5 states by threat
    state_scores: Dict[str, List[float]] = {}
    for f in scored:
        state = (
            f["properties"].get("state", "")
            or (f["properties"].get("location", {}) or {}).get("state", "")
        )
        if state and state != "—" and state != "Unknown":
            state_scores.setdefault(state, []).append(
                f["properties"]["threat_score"]
            )

    top_states: List[Dict] = []
    for state, state_score_list in state_scores.items():
        top_states.append({
            "state": state,
            "hotspot_count": len(state_score_list),
            "mean_score": round(sum(state_score_list) / len(state_score_list), 1),
            "max_score": max(state_score_list),
            "critical_count": sum(1 for s in state_score_list if s >= 80),
        })
    top_states.sort(key=lambda x: x["max_score"], reverse=True)

    print(
        f"[SCORE] Scored {len(scored)} hotspots: "
        f"CRITICAL={critical_count}, HIGH={high_count}, "
        f"ELEVATED={elevated_count}, MONITOR={monitor_count}, "
        f"top={top_score}, mean={mean_score}"
    )

    return {
        **geojson,
        "features": scored,
        "metadata": {
            **geojson.get("metadata", {}),
            "scored": True,
            "critical_count": critical_count,
            "high_count": high_count,
            "elevated_count": elevated_count,
            "monitor_count": monitor_count,
            "top_score": top_score,
            "mean_score": mean_score,
            "top_threat_states": top_states[:10],
        },
    }