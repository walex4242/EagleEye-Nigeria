"""
utils/geocoding.py
──────────────────
Reverse geocoding for Nigeria — converts lat/lon to human-readable
location names (state, LGA, nearest town) for operational use.

Uses:
  1. Local Nigeria state/LGA boundary lookup (instant, offline)
  2. OpenStreetMap Nominatim API for nearest town (cached)
  3. Military-grade coordinate formatting (DMS, MGRS-style)
"""

from __future__ import annotations

import os
import time
import hashlib
import logging
import requests
from math import radians, cos, sin, asin, sqrt, degrees, floor
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger("eagleeye.geocoding")

# ── Rate limiting for Nominatim (max 1 req/sec) ──────────────
_last_nominatim_call: float = 0.0
NOMINATIM_MIN_INTERVAL = 1.1  # seconds

# ── Cache directory ───────────────────────────────────────────
GEOCODE_CACHE_DIR = Path("./data/geocode_cache")
GEOCODE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory cache ──────────────────────────────────────────
_geocode_cache: Dict[str, Dict] = {}


# ── Nigeria Administrative Boundaries ─────────────────────────
# All 36 states + FCT with approximate bounding boxes
# Format: "state_name": (min_lat, max_lat, min_lon, max_lon, capital)

NIGERIA_STATES: Dict[str, Dict] = {
    "Abia": {"bounds": (4.75, 6.12, 7.00, 8.00), "capital": "Umuahia", "geo_zone": "South East"},
    "Adamawa": {"bounds": (7.48, 10.96, 11.40, 13.70), "capital": "Yola", "geo_zone": "North East"},
    "Akwa Ibom": {"bounds": (4.32, 5.53, 7.35, 8.30), "capital": "Uyo", "geo_zone": "South South"},
    "Anambra": {"bounds": (5.68, 6.77, 6.60, 7.20), "capital": "Awka", "geo_zone": "South East"},
    "Bauchi": {"bounds": (9.30, 12.22, 8.50, 11.00), "capital": "Bauchi", "geo_zone": "North East"},
    "Bayelsa": {"bounds": (4.20, 5.35, 5.20, 6.80), "capital": "Yenagoa", "geo_zone": "South South"},
    "Benue": {"bounds": (6.40, 8.10, 6.70, 10.00), "capital": "Makurdi", "geo_zone": "North Central"},
    "Borno": {"bounds": (10.00, 13.70, 11.50, 14.70), "capital": "Maiduguri", "geo_zone": "North East"},
    "Cross River": {"bounds": (4.28, 6.88, 7.70, 9.45), "capital": "Calabar", "geo_zone": "South South"},
    "Delta": {"bounds": (5.05, 6.50, 5.00, 6.80), "capital": "Asaba", "geo_zone": "South South"},
    "Ebonyi": {"bounds": (5.70, 6.70, 7.60, 8.30), "capital": "Abakaliki", "geo_zone": "South East"},
    "Edo": {"bounds": (5.70, 7.60, 5.00, 6.70), "capital": "Benin City", "geo_zone": "South South"},
    "Ekiti": {"bounds": (7.25, 8.10, 4.70, 5.80), "capital": "Ado Ekiti", "geo_zone": "South West"},
    "Enugu": {"bounds": (5.90, 7.10, 6.95, 7.85), "capital": "Enugu", "geo_zone": "South East"},
    "FCT": {"bounds": (8.40, 9.45, 6.70, 7.60), "capital": "Abuja", "geo_zone": "North Central"},
    "Gombe": {"bounds": (9.30, 11.20, 10.70, 12.00), "capital": "Gombe", "geo_zone": "North East"},
    "Imo": {"bounds": (5.10, 6.00, 6.60, 7.50), "capital": "Owerri", "geo_zone": "South East"},
    "Jigawa": {"bounds": (11.00, 13.00, 8.00, 10.50), "capital": "Dutse", "geo_zone": "North West"},
    "Kaduna": {"bounds": (9.00, 11.30, 6.00, 8.80), "capital": "Kaduna", "geo_zone": "North West"},
    "Kano": {"bounds": (10.30, 12.70, 7.60, 9.40), "capital": "Kano", "geo_zone": "North West"},
    "Katsina": {"bounds": (11.00, 13.40, 6.50, 8.60), "capital": "Katsina", "geo_zone": "North West"},
    "Kebbi": {"bounds": (10.50, 13.30, 3.40, 5.80), "capital": "Birnin Kebbi", "geo_zone": "North West"},
    "Kogi": {"bounds": (6.70, 8.70, 5.40, 7.80), "capital": "Lokoja", "geo_zone": "North Central"},
    "Kwara": {"bounds": (7.70, 9.80, 2.70, 6.00), "capital": "Ilorin", "geo_zone": "North Central"},
    "Lagos": {"bounds": (6.38, 6.70, 2.70, 4.35), "capital": "Ikeja", "geo_zone": "South West"},
    "Nasarawa": {"bounds": (7.70, 9.30, 7.00, 9.40), "capital": "Lafia", "geo_zone": "North Central"},
    "Niger": {"bounds": (8.30, 11.50, 3.50, 7.50), "capital": "Minna", "geo_zone": "North Central"},
    "Ogun": {"bounds": (6.30, 7.80, 2.70, 4.60), "capital": "Abeokuta", "geo_zone": "South West"},
    "Ondo": {"bounds": (5.75, 7.80, 4.30, 6.00), "capital": "Akure", "geo_zone": "South West"},
    "Osun": {"bounds": (7.00, 8.10, 4.00, 5.10), "capital": "Osogbo", "geo_zone": "South West"},
    "Oyo": {"bounds": (7.10, 9.10, 2.70, 4.60), "capital": "Ibadan", "geo_zone": "South West"},
    "Plateau": {"bounds": (8.50, 10.60, 8.20, 10.10), "capital": "Jos", "geo_zone": "North Central"},
    "Rivers": {"bounds": (4.25, 5.70, 6.50, 7.60), "capital": "Port Harcourt", "geo_zone": "South South"},
    "Sokoto": {"bounds": (11.50, 13.80, 4.00, 6.50), "capital": "Sokoto", "geo_zone": "North West"},
    "Taraba": {"bounds": (6.50, 9.60, 9.30, 11.90), "capital": "Jalingo", "geo_zone": "North East"},
    "Yobe": {"bounds": (10.50, 13.30, 9.80, 12.30), "capital": "Damaturu", "geo_zone": "North East"},
    "Zamfara": {"bounds": (11.00, 13.10, 5.40, 7.50), "capital": "Gusau", "geo_zone": "North West"},
}

# Major Nigerian towns/cities with coordinates for distance calculation
NIGERIA_TOWNS: List[Dict] = [
    # Northeast (Boko Haram corridor)
    {"name": "Maiduguri", "lat": 11.8469, "lon": 13.1573, "state": "Borno", "type": "state_capital"},
    {"name": "Bama", "lat": 11.5204, "lon": 13.6856, "state": "Borno", "type": "town"},
    {"name": "Gwoza", "lat": 11.0833, "lon": 13.6953, "state": "Borno", "type": "town"},
    {"name": "Chibok", "lat": 10.9000, "lon": 12.8333, "state": "Borno", "type": "town"},
    {"name": "Konduga", "lat": 11.6500, "lon": 13.2667, "state": "Borno", "type": "town"},
    {"name": "Dikwa", "lat": 12.0333, "lon": 13.9167, "state": "Borno", "type": "town"},
    {"name": "Monguno", "lat": 12.6700, "lon": 13.6100, "state": "Borno", "type": "town"},
    {"name": "Damboa", "lat": 11.1553, "lon": 12.7564, "state": "Borno", "type": "town"},
    {"name": "Kukawa", "lat": 12.9236, "lon": 13.5656, "state": "Borno", "type": "town"},
    {"name": "Damaturu", "lat": 11.7470, "lon": 11.9609, "state": "Yobe", "type": "state_capital"},
    {"name": "Potiskum", "lat": 11.7128, "lon": 11.0780, "state": "Yobe", "type": "town"},
    {"name": "Gashua", "lat": 12.8711, "lon": 11.0469, "state": "Yobe", "type": "town"},
    {"name": "Yola", "lat": 9.2035, "lon": 12.4954, "state": "Adamawa", "type": "state_capital"},
    {"name": "Mubi", "lat": 10.2677, "lon": 13.2640, "state": "Adamawa", "type": "town"},
    {"name": "Michika", "lat": 10.6214, "lon": 13.3981, "state": "Adamawa", "type": "town"},
    {"name": "Gombe", "lat": 10.2897, "lon": 11.1711, "state": "Gombe", "type": "state_capital"},
    {"name": "Bauchi", "lat": 10.3103, "lon": 9.8439, "state": "Bauchi", "type": "state_capital"},

    # Northwest (Banditry corridor)
    {"name": "Gusau", "lat": 12.1704, "lon": 6.6612, "state": "Zamfara", "type": "state_capital"},
    {"name": "Anka", "lat": 12.1094, "lon": 5.9275, "state": "Zamfara", "type": "town"},
    {"name": "Shinkafi", "lat": 13.0667, "lon": 6.5000, "state": "Zamfara", "type": "town"},
    {"name": "Tsafe", "lat": 12.1667, "lon": 6.9167, "state": "Zamfara", "type": "town"},
    {"name": "Maru", "lat": 12.3333, "lon": 6.4000, "state": "Zamfara", "type": "town"},
    {"name": "Katsina", "lat": 13.0059, "lon": 7.5986, "state": "Katsina", "type": "state_capital"},
    {"name": "Jibia", "lat": 13.3500, "lon": 7.2333, "state": "Katsina", "type": "town"},
    {"name": "Batsari", "lat": 12.8833, "lon": 7.2667, "state": "Katsina", "type": "town"},
    {"name": "Dan Sadau", "lat": 12.4500, "lon": 6.2667, "state": "Zamfara", "type": "town"},
    {"name": "Kaduna", "lat": 10.5222, "lon": 7.4383, "state": "Kaduna", "type": "state_capital"},
    {"name": "Zaria", "lat": 11.0855, "lon": 7.7106, "state": "Kaduna", "type": "city"},
    {"name": "Kafanchan", "lat": 9.5833, "lon": 8.3000, "state": "Kaduna", "type": "town"},
    {"name": "Birnin Gwari", "lat": 10.7833, "lon": 6.5167, "state": "Kaduna", "type": "town"},
    {"name": "Sokoto", "lat": 13.0607, "lon": 5.2401, "state": "Sokoto", "type": "state_capital"},
    {"name": "Kano", "lat": 12.0022, "lon": 8.5920, "state": "Kano", "type": "state_capital"},

    # North Central (Herder-farmer belt)
    {"name": "Makurdi", "lat": 7.7337, "lon": 8.5217, "state": "Benue", "type": "state_capital"},
    {"name": "Jos", "lat": 9.8965, "lon": 8.8583, "state": "Plateau", "type": "state_capital"},
    {"name": "Lafia", "lat": 8.4966, "lon": 8.5157, "state": "Nasarawa", "type": "state_capital"},
    {"name": "Lokoja", "lat": 7.7969, "lon": 6.7433, "state": "Kogi", "type": "state_capital"},
    {"name": "Minna", "lat": 9.6139, "lon": 6.5569, "state": "Niger", "type": "state_capital"},
    {"name": "Abuja", "lat": 9.0579, "lon": 7.4951, "state": "FCT", "type": "federal_capital"},
    {"name": "Ilorin", "lat": 8.5000, "lon": 4.5500, "state": "Kwara", "type": "state_capital"},
    {"name": "Gboko", "lat": 7.3167, "lon": 9.0000, "state": "Benue", "type": "town"},
    {"name": "Otukpo", "lat": 7.1905, "lon": 8.1300, "state": "Benue", "type": "town"},

    # Niger Delta
    {"name": "Port Harcourt", "lat": 4.8156, "lon": 7.0498, "state": "Rivers", "type": "state_capital"},
    {"name": "Warri", "lat": 5.5167, "lon": 5.7500, "state": "Delta", "type": "city"},
    {"name": "Yenagoa", "lat": 4.9267, "lon": 6.2676, "state": "Bayelsa", "type": "state_capital"},
    {"name": "Asaba", "lat": 6.1944, "lon": 6.7333, "state": "Delta", "type": "state_capital"},
    {"name": "Benin City", "lat": 6.3350, "lon": 5.6037, "state": "Edo", "type": "state_capital"},
    {"name": "Calabar", "lat": 4.9517, "lon": 8.3220, "state": "Cross River", "type": "state_capital"},
    {"name": "Uyo", "lat": 5.0510, "lon": 7.9335, "state": "Akwa Ibom", "type": "state_capital"},
    {"name": "Bonny", "lat": 4.4333, "lon": 7.1667, "state": "Rivers", "type": "town"},

    # Southwest
    {"name": "Lagos", "lat": 6.5244, "lon": 3.3792, "state": "Lagos", "type": "megacity"},
    {"name": "Ibadan", "lat": 7.3878, "lon": 3.8963, "state": "Oyo", "type": "state_capital"},
    {"name": "Abeokuta", "lat": 7.1557, "lon": 3.3453, "state": "Ogun", "type": "state_capital"},
    {"name": "Akure", "lat": 7.2526, "lon": 5.1931, "state": "Ondo", "type": "state_capital"},
    {"name": "Osogbo", "lat": 7.7827, "lon": 4.5418, "state": "Osun", "type": "state_capital"},
    {"name": "Ado Ekiti", "lat": 7.6211, "lon": 5.2214, "state": "Ekiti", "type": "state_capital"},

    # Southeast
    {"name": "Enugu", "lat": 6.4584, "lon": 7.5464, "state": "Enugu", "type": "state_capital"},
    {"name": "Owerri", "lat": 5.4851, "lon": 7.0352, "state": "Imo", "type": "state_capital"},
    {"name": "Awka", "lat": 6.2106, "lon": 7.0742, "state": "Anambra", "type": "state_capital"},
    {"name": "Umuahia", "lat": 5.5264, "lon": 7.4906, "state": "Abia", "type": "state_capital"},
    {"name": "Abakaliki", "lat": 6.3249, "lon": 8.1137, "state": "Ebonyi", "type": "state_capital"},
]


# ── Data Classes ──────────────────────────────────────────────

@dataclass
class LocationInfo:
    """Structured location information for a coordinate."""
    latitude: float
    longitude: float
    state: str
    lga: str
    nearest_town: str
    nearest_town_distance_km: float
    nearest_town_direction: str
    geo_zone: str
    state_capital: str
    coords_dms: str
    google_maps_url: str
    operational_description: str
    nominatim_place: Optional[str] = None
    road: Optional[str] = None
    additional_context: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Haversine ─────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * asin(sqrt(a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate bearing in degrees from point 1 to point 2."""
    lat1_r, lat2_r = radians(lat1), radians(lat2)
    dlon_r = radians(lon2 - lon1)
    x = sin(dlon_r) * cos(lat2_r)
    y = cos(lat1_r) * sin(lat2_r) - sin(lat1_r) * cos(lat2_r) * cos(dlon_r)
    bearing = degrees(asin(min(1, max(-1, x / max(sqrt(x**2 + y**2), 1e-10)))))
    # Normalize to 0-360
    import math
    bearing_deg = math.degrees(math.atan2(x, y))
    return (bearing_deg + 360) % 360


def _bearing_to_compass(bearing: float) -> str:
    """Convert bearing in degrees to compass direction."""
    directions = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    idx = round(bearing / 22.5) % 16
    return directions[idx]


def _decimal_to_dms(lat: float, lon: float) -> str:
    """Convert decimal degrees to DMS format (military standard)."""
    def _to_dms(deg: float, is_lat: bool) -> str:
        direction = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
        deg = abs(deg)
        d = int(deg)
        m = int((deg - d) * 60)
        s = ((deg - d) * 60 - m) * 60
        return f"{d}°{m:02d}'{s:05.2f}\"{direction}"

    return f"{_to_dms(lat, True)} {_to_dms(lon, False)}"


# ── State Lookup ──────────────────────────────────────────────

def _find_state(lat: float, lon: float) -> Tuple[str, str, str]:
    """
    Find the Nigerian state for a given coordinate.
    Returns (state_name, state_capital, geo_zone).
    Uses bounding box containment with overlap resolution.
    """
    candidates: List[Tuple[str, Dict, float]] = []

    for state_name, info in NIGERIA_STATES.items():
        min_lat, max_lat, min_lon, max_lon = info["bounds"]
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            # Calculate distance to bbox center for tie-breaking
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2
            dist = _haversine(lat, lon, center_lat, center_lon)
            candidates.append((state_name, info, dist))

    if candidates:
        # Pick the closest center (handles overlapping bboxes)
        candidates.sort(key=lambda x: x[2])
        best = candidates[0]
        return best[0], best[1]["capital"], best[1]["geo_zone"]

    # Fallback: find nearest state center
    best_dist = float("inf")
    best_state = "Unknown"
    best_capital = "Unknown"
    best_zone = "Unknown"

    for state_name, info in NIGERIA_STATES.items():
        min_lat, max_lat, min_lon, max_lon = info["bounds"]
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        dist = _haversine(lat, lon, center_lat, center_lon)
        if dist < best_dist:
            best_dist = dist
            best_state = state_name
            best_capital = info["capital"]
            best_zone = info["geo_zone"]

    return best_state, best_capital, best_zone


# ── Nearest Town Lookup ───────────────────────────────────────

def _find_nearest_town(
    lat: float, lon: float, max_results: int = 3,
) -> List[Dict]:
    """Find the nearest known towns to a coordinate."""
    distances: List[Dict] = []

    for town in NIGERIA_TOWNS:
        dist = _haversine(lat, lon, town["lat"], town["lon"])
        bearing = _bearing(town["lat"], town["lon"], lat, lon)
        compass = _bearing_to_compass(bearing)

        distances.append({
            "name": town["name"],
            "state": town["state"],
            "type": town["type"],
            "distance_km": round(dist, 1),
            "direction": compass,
            "bearing": round(bearing, 1),
        })

    distances.sort(key=lambda x: x["distance_km"])
    return distances[:max_results]


# ── Nominatim Reverse Geocoding ───────────────────────────────

def _nominatim_reverse(
    lat: float, lon: float,
) -> Optional[Dict]:
    """
    Reverse geocode using OpenStreetMap Nominatim.
    Rate-limited to 1 request per second.
    Results are cached to disk.
    """
    global _last_nominatim_call

    # Round to ~100m precision for cache efficiency
    cache_lat = round(lat, 3)
    cache_lon = round(lon, 3)
    cache_key = f"{cache_lat}_{cache_lon}"

    # Check in-memory cache
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    # Check disk cache
    cache_file = GEOCODE_CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
                _geocode_cache[cache_key] = data
                return data
        except Exception:
            pass

    # Rate limiting
    now = time.time()
    elapsed = now - _last_nominatim_call
    if elapsed < NOMINATIM_MIN_INTERVAL:
        time.sleep(NOMINATIM_MIN_INTERVAL - elapsed)

    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "zoom": 14,
            "addressdetails": 1,
        }
        headers = {
            "User-Agent": "EagleEye-Nigeria/1.0 (security monitoring)",
        }

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        _last_nominatim_call = time.time()

        if resp.status_code == 200:
            data = resp.json()
            # Cache to memory and disk
            _geocode_cache[cache_key] = data
            try:
                with open(cache_file, "w") as f:
                    json.dump(data, f)
            except Exception:
                pass
            return data

    except Exception as e:
        logger.warning("Nominatim reverse geocoding failed: %s", e)

    return None


# ── Main Geocoding Function ──────────────────────────────────

def reverse_geocode(
    lat: float,
    lon: float,
    use_nominatim: bool = True,
) -> LocationInfo:
    """
    Full reverse geocoding for a Nigerian coordinate.

    Returns structured location info including:
    - State, LGA, geopolitical zone
    - Nearest known town with distance and direction
    - DMS coordinates
    - Google Maps link
    - Operational description for military briefings
    - Optional Nominatim place name
    """
    # ── Local lookups (instant) ──
    state, state_capital, geo_zone = _find_state(lat, lon)
    nearest_towns = _find_nearest_town(lat, lon)
    nearest = nearest_towns[0] if nearest_towns else {
        "name": "Unknown",
        "distance_km": 0,
        "direction": "N",
    }

    coords_dms = _decimal_to_dms(lat, lon)

    # Google Maps URL with zoom level 15 (street level)
    google_maps_url = (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={lat},{lon}"
    )

    # ── Nominatim lookup (optional, cached) ──
    nominatim_place = None
    road = None
    lga = ""

    if use_nominatim:
        nom = _nominatim_reverse(lat, lon)
        if nom:
            address = nom.get("address", {})
            nominatim_place = nom.get("display_name", "")

            # Extract LGA (various Nominatim field names)
            lga = (
                address.get("county", "")
                or address.get("state_district", "")
                or address.get("city_district", "")
                or address.get("municipality", "")
                or ""
            )

            road = address.get("road", "") or address.get("hamlet", "")

            # Try to get more specific place name
            for field in ("village", "town", "city", "hamlet", "suburb", "neighbourhood"):
                place = address.get(field)
                if place:
                    nominatim_place = place
                    break

    if not lga:
        lga = f"Near {nearest['name']}"

    # ── Build operational description ──
    dist = nearest["distance_km"]
    direction = nearest["direction"]

    if dist < 2:
        proximity = f"within {nearest['name']}"
    elif dist < 10:
        proximity = f"{dist:.1f}km {direction} of {nearest['name']}"
    elif dist < 50:
        proximity = f"{dist:.0f}km {direction} of {nearest['name']}"
    else:
        proximity = f"approx {dist:.0f}km {direction} of {nearest['name']}"

    specific_place = ""
    if nominatim_place and nominatim_place != nearest["name"]:
        specific_place = f" ({nominatim_place})"

    operational_description = (
        f"{proximity}{specific_place}, "
        f"{lga}, {state} State, {geo_zone}"
    )

    # ── Additional context for military ──
    additional_context = None
    if len(nearest_towns) >= 2:
        t2 = nearest_towns[1]
        additional_context = (
            f"Also {t2['distance_km']:.0f}km {t2['direction']} of "
            f"{t2['name']}. State capital {state_capital} is "
            f"{_haversine(lat, lon, *_get_town_coords(state_capital)):.0f}km away."
        )

    return LocationInfo(
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        state=state,
        lga=lga,
        nearest_town=nearest["name"],
        nearest_town_distance_km=nearest["distance_km"],
        nearest_town_direction=direction,
        geo_zone=geo_zone,
        state_capital=state_capital,
        coords_dms=coords_dms,
        google_maps_url=google_maps_url,
        operational_description=operational_description,
        nominatim_place=nominatim_place,
        road=road,
        additional_context=additional_context,
    )


def _get_town_coords(town_name: str) -> Tuple[float, float]:
    """Get coordinates for a town name."""
    for town in NIGERIA_TOWNS:
        if town["name"] == town_name:
            return town["lat"], town["lon"]
    return 9.0, 7.5  # Default to Abuja


# ── Batch Geocoding ───────────────────────────────────────────

def enrich_features_with_location(
    geojson: Dict,
    use_nominatim: bool = True,
    max_nominatim_calls: int = 50,
) -> Dict:
    """
    Enrich a GeoJSON FeatureCollection by adding location info
    to every feature's properties.

    For efficiency:
    - Local state/town lookup for ALL features (instant)
    - Nominatim calls are batched and capped at max_nominatim_calls
    - Nearby features share the same Nominatim result (grid-based)
    """
    features = geojson.get("features", [])
    if not features:
        return geojson

    print(f"[GEO] Enriching {len(features)} features with location data...")

    nominatim_calls = 0
    # Grid-based Nominatim dedup (round to ~1km cells)
    nominatim_grid: Dict[str, Optional[Dict]] = {}

    enriched_features: List[Dict] = []

    for i, feature in enumerate(features):
        coords = feature.get("geometry", {}).get("coordinates", [0, 0])
        lon = float(coords[0]) if len(coords) > 0 else 0.0
        lat = float(coords[1]) if len(coords) > 1 else 0.0

        if lat == 0 and lon == 0:
            enriched_features.append(feature)
            continue

        # Decide whether to use Nominatim for this feature
        grid_key = f"{round(lat, 2)}_{round(lon, 2)}"
        do_nominatim = (
            use_nominatim
            and nominatim_calls < max_nominatim_calls
            and grid_key not in nominatim_grid
        )

        if do_nominatim:
            nominatim_calls += 1

        # Check if we already have Nominatim data for this grid cell
        skip_nominatim = grid_key in nominatim_grid

        location = reverse_geocode(
            lat, lon,
            use_nominatim=do_nominatim or skip_nominatim,
        )

        if do_nominatim:
            nominatim_grid[grid_key] = {
                "place": location.nominatim_place,
                "road": location.road,
            }

        # Merge location into feature properties
        props = feature.get("properties", {})
        props["location"] = {
            "state": location.state,
            "lga": location.lga,
            "nearest_town": location.nearest_town,
            "distance_km": location.nearest_town_distance_km,
            "direction": location.nearest_town_direction,
            "geo_zone": location.geo_zone,
            "coords_dms": location.coords_dms,
            "operational_description": location.operational_description,
        }
        props["google_maps_url"] = location.google_maps_url
        props["state"] = location.state
        props["lga"] = location.lga
        props["nearest_town"] = location.nearest_town

        if location.nominatim_place:
            props["location"]["place_name"] = location.nominatim_place
        if location.road:
            props["location"]["road"] = location.road
        if location.additional_context:
            props["location"]["additional_context"] = location.additional_context

        enriched_feature = {**feature, "properties": props}
        enriched_features.append(enriched_feature)

    print(
        f"[GEO] ✓ Enriched {len(enriched_features)} features "
        f"({nominatim_calls} Nominatim calls)"
    )

    return {
        **geojson,
        "features": enriched_features,
    }


# ── Quick Location Label ─────────────────────────────────────

def quick_label(lat: float, lon: float) -> str:
    """
    Fast location label without Nominatim.
    Returns e.g. "12.5km NE of Maiduguri, Borno State"
    """
    state, _, _ = _find_state(lat, lon)
    nearest = _find_nearest_town(lat, lon, max_results=1)

    if nearest:
        t = nearest[0]
        if t["distance_km"] < 2:
            return f"{t['name']}, {state} State"
        return (
            f"{t['distance_km']:.1f}km {t['direction']} of "
            f"{t['name']}, {state} State"
        )

    return f"{lat:.4f}°N, {lon:.4f}°E, {state} State"