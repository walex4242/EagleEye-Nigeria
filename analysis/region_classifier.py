"""
region_classifier.py
─────────────────────
Maps lat/lon coordinates to Nigerian states and security zones.
Used to enrich hotspot data with administrative context.

Note: Bounding boxes are approximate. For production use,
replace with proper GeoJSON shapefiles for exact boundaries.
"""

from __future__ import annotations
from math import sqrt


# Simplified bounding boxes for Nigerian states
# Format: state_name: (min_lat, max_lat, min_lon, max_lon)
#
# IMPORTANT: Order matters! More specific / smaller states should come
# before larger overlapping ones. Borno (large) must come after Yobe, etc.
NIGERIAN_STATES_ORDERED: list[tuple[str, tuple[float, float, float, float]]] = [
    # ── Tier 1: Active Conflict (checked first for priority) ──
    ("Zamfara",      (11.5, 13.5,  5.8,  7.8)),
    ("Sokoto",       (12.0, 13.9,  4.1,  6.0)),
    ("Katsina",      (11.5, 13.8,  6.8,  9.3)),
    ("Yobe",         (11.0, 14.0, 10.5, 12.8)),
    ("Borno",        (10.0, 14.0, 12.5, 15.2)),

    # ── Tier 2: Elevated Risk ──
    ("Kebbi",        (10.5, 13.0,  3.5,  5.8)),
    ("Niger",        ( 8.5, 11.5,  3.5,  7.0)),
    ("Kaduna",       ( 9.0, 11.5,  7.0,  8.5)),
    ("Kano",         (11.0, 13.0,  8.0,  9.5)),
    ("Adamawa",      ( 7.5, 10.5, 12.0, 14.0)),
    ("Gombe",        ( 9.5, 11.0, 10.5, 12.0)),
    ("Plateau",      ( 8.5, 10.5,  8.5, 10.2)),

    # ── Tier 3: Monitored ──
    ("Jigawa",       (11.5, 13.5,  8.5, 10.8)),
    ("Bauchi",       ( 9.5, 11.5,  9.0, 10.8)),
    ("Nasarawa",     ( 7.8,  9.2,  7.5,  9.5)),
    ("Benue",        ( 6.5,  8.5,  7.5, 10.0)),
    ("Taraba",       ( 6.5,  9.5, 10.0, 12.0)),
    ("Kogi",         ( 6.5,  8.5,  5.5,  7.8)),

    # ── FCT ──
    ("FCT Abuja",    ( 8.3,  9.3,  6.8,  7.8)),

    # ── Other Northern States ──
    ("Kwara",        ( 7.8, 10.0,  3.5,  6.0)),

    # ── Southwest ──
    ("Lagos",        ( 6.3,  6.8,  2.7,  3.8)),
    ("Ogun",         ( 6.6,  7.8,  2.7,  4.0)),
    ("Oyo",          ( 7.0,  9.0,  3.0,  5.0)),
    ("Osun",         ( 7.0,  8.2,  4.0,  5.0)),
    ("Ekiti",        ( 7.3,  8.1,  4.8,  5.8)),
    ("Ondo",         ( 5.8,  7.8,  4.3,  6.0)),

    # ── South-South (PREVIOUSLY MISSING: Edo) ──
    ("Edo",          ( 5.8,  7.5,  5.0,  6.8)),

    # ── Southeast / South-South ──
    ("Enugu",        ( 6.0,  7.0,  7.0,  7.8)),
    ("Anambra",      ( 5.8,  6.8,  6.5,  7.2)),
    ("Ebonyi",       ( 5.8,  6.8,  7.8,  8.5)),
    ("Abia",         ( 5.0,  6.0,  7.0,  8.0)),
    ("Imo",          ( 5.0,  6.0,  6.5,  7.5)),
    ("Rivers",       ( 4.3,  5.5,  6.5,  7.6)),
    ("Bayelsa",      ( 4.2,  5.3,  5.5,  6.8)),
    ("Delta",        ( 5.0,  6.5,  5.0,  6.8)),
    ("Cross River",  ( 4.5,  7.0,  7.8,  9.5)),
    ("Akwa Ibom",    ( 4.5,  5.5,  7.3,  8.3)),
]


# Security threat tiers
THREAT_TIERS: dict[str, list[str]] = {
    "Tier 1 — Active Conflict":  ["Zamfara", "Borno", "Yobe", "Katsina", "Sokoto"],
    "Tier 2 — Elevated Risk":    ["Kaduna", "Niger", "Kebbi", "Adamawa", "Gombe", "Plateau"],
    "Tier 3 — Monitored":        ["Bauchi", "Jigawa", "Nasarawa", "Taraba", "Kogi", "Benue"],
}


# ══════════════════════════════════════════════════════════════
# STATE CENTER COORDINATES (for nearest-match fallback)
# ══════════════════════════════════════════════════════════════

_STATE_CENTERS: dict[str, tuple[float, float]] = {
    "Abia": (5.45, 7.52),
    "Adamawa": (9.33, 12.40),
    "Akwa Ibom": (5.01, 7.85),
    "Anambra": (6.21, 6.94),
    "Bauchi": (10.31, 9.84),
    "Bayelsa": (4.77, 6.07),
    "Benue": (7.34, 8.77),
    "Borno": (11.85, 13.15),
    "Cross River": (5.87, 8.53),
    "Delta": (5.53, 5.90),
    "Ebonyi": (6.26, 8.07),
    "Edo": (6.63, 5.93),
    "Ekiti": (7.72, 5.31),
    "Enugu": (6.44, 7.50),
    "FCT Abuja": (9.06, 7.49),
    "Gombe": (10.29, 11.17),
    "Imo": (5.57, 7.06),
    "Jigawa": (12.23, 9.56),
    "Kaduna": (10.52, 7.43),
    "Kano": (12.00, 8.52),
    "Katsina": (12.99, 7.60),
    "Kebbi": (12.45, 4.20),
    "Kogi": (7.73, 6.69),
    "Kwara": (8.49, 4.54),
    "Lagos": (6.52, 3.38),
    "Nasarawa": (8.54, 8.52),
    "Niger": (9.93, 5.60),
    "Ogun": (6.97, 3.47),
    "Ondo": (7.25, 5.19),
    "Osun": (7.56, 4.52),
    "Oyo": (7.84, 3.93),
    "Plateau": (9.22, 9.52),
    "Rivers": (4.84, 6.92),
    "Sokoto": (13.06, 5.24),
    "Taraba": (7.87, 10.70),
    "Yobe": (12.29, 11.44),
    "Zamfara": (12.17, 6.66),
}

# Nigeria approximate bounding box for "is this even in Nigeria?" check
_NIGERIA_BOUNDS = (4.0, 14.5, 2.5, 15.5)  # min_lat, max_lat, min_lon, max_lon


def classify_region(lat: float, lon: float) -> dict:
    """
    Return state and threat tier for a given coordinate.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        dict with 'state' and 'threat_tier' keys.
    """
    state = _find_state(lat, lon)
    tier = _find_threat_tier(state)
    return {"state": state, "threat_tier": tier}


def _find_state(lat: float, lon: float) -> str:
    """
    Find the Nigerian state for given coordinates.
    
    Strategy:
      1. Try bounding box match (fast, ordered by priority)
      2. If no match AND point is inside Nigeria, fall back to nearest-center
      3. If point is outside Nigeria entirely, return 'Outside Nigeria'
    """
    # Step 1: Bounding box match
    for state, (min_lat, max_lat, min_lon, max_lon) in NIGERIAN_STATES_ORDERED:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return state

    # Step 2: Check if coordinate is inside Nigeria at all
    min_lat, max_lat, min_lon, max_lon = _NIGERIA_BOUNDS
    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
        return "Outside Nigeria"

    # Step 3: Nearest state center fallback (only for points inside Nigeria)
    return _nearest_state_center(lat, lon)


def _nearest_state_center(lat: float, lon: float) -> str:
    """
    Find the nearest Nigerian state by center-point distance.
    Used as fallback when bounding boxes don't match.
    """
    min_distance = float("inf")
    nearest_state = "Unknown"

    for state_name, (s_lat, s_lon) in _STATE_CENTERS.items():
        distance = sqrt((lat - s_lat) ** 2 + (lon - s_lon) ** 2)
        if distance < min_distance:
            min_distance = distance
            nearest_state = state_name

    return nearest_state


def _find_threat_tier(state: str) -> str:
    """Return the security threat tier for a given state."""
    for tier, states in THREAT_TIERS.items():
        if state in states:
            return tier
    return "Tier 4 — Standard Monitoring"


def enrich_with_regions(geojson: dict) -> dict:
    """
    Add 'state' and 'threat_tier' to every feature in a GeoJSON FeatureCollection.
    """
    enriched_features: list[dict] = []

    for feature in geojson.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            region = classify_region(lat, lon)
            props = {**feature.get("properties", {}), **region}
            enriched_features.append({**feature, "properties": props})
        else:
            enriched_features.append(feature)

    return {**geojson, "features": enriched_features}


def get_all_states() -> list[str]:
    """Return a list of all Nigerian state names."""
    return [name for name, _ in NIGERIAN_STATES_ORDERED]


def get_threat_tier_states(tier_keyword: str) -> list[str]:
    """Return states matching a tier keyword (e.g., 'Tier 1')."""
    for tier, states in THREAT_TIERS.items():
        if tier_keyword.lower() in tier.lower():
            return states
    return []


def get_state_from_coords(lat: float, lon: float) -> str:
    """
    Resolve coordinates to a Nigerian state name.

    Uses bounding box first, then nearest-state-center fallback
    so we minimize 'Unknown' results.

    Args:
        lat: Latitude (decimal degrees)
        lon: Longitude (decimal degrees)

    Returns:
        Nigerian state name (e.g., 'Zamfara', 'Borno')
    """
    return _find_state(lat, lon)