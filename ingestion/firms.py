"""
firms.py
─────────
Fetches thermal hotspot data from NASA FIRMS API with caching.
"""

import os
import requests
import csv
import io
import traceback
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ingestion.cache import firms_cache

FIRMS_API_KEY = os.getenv("NASA_FIRMS_API_KEY", "")
FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

NIGERIA_BOUNDS = {
    "min_lat": 4.0,
    "max_lat": 14.0,
    "min_lon": 2.7,
    "max_lon": 15.0,
}

RED_ZONES = [
    {"name": "Northwest Corridor", "min_lat": 11.0, "max_lat": 14.0, "min_lon": 4.0, "max_lon": 9.0},
    {"name": "Northeast Corridor", "min_lat": 10.0, "max_lat": 14.0, "min_lon": 11.0, "max_lon": 15.0},
    {"name": "North Central", "min_lat": 8.0, "max_lat": 11.0, "min_lon": 5.0, "max_lon": 10.0},
]

FIRMS_SOURCES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "MODIS_NRT",
]


def _get_red_zone(lat: float, lon: float) -> str:
    for zone in RED_ZONES:
        if zone["min_lat"] <= lat <= zone["max_lat"] and zone["min_lon"] <= lon <= zone["max_lon"]:
            return zone["name"]
    return "Other"


def _is_in_nigeria(lat: float, lon: float) -> bool:
    return (
        NIGERIA_BOUNDS["min_lat"] <= lat <= NIGERIA_BOUNDS["max_lat"]
        and NIGERIA_BOUNDS["min_lon"] <= lon <= NIGERIA_BOUNDS["max_lon"]
    )


def _validate_api_key(key: str) -> bool:
    if not key or len(key) < 10:
        return False
    return True


def fetch_hotspots(days: int = 1, country: str = "NGA") -> dict:
    """
    Fetch thermal hotspot data from NASA FIRMS API.
    Results are cached for 5 minutes to prevent duplicate API calls.
    """
    # ── Check cache first ──
    cache_key = f"firms_{country}_{days}"
    cached = firms_cache.get(cache_key)
    if cached is not None:
        print(f"[FIRMS] ✓ Cache hit for {cache_key} ({cached['metadata']['count']} features)")
        return cached

    print(f"[FIRMS] Cache miss for {cache_key} — fetching from API...")

    if not _validate_api_key(FIRMS_API_KEY):
        print("[INFO] No valid NASA_FIRMS_API_KEY found — returning mock data.")
        result = _mock_hotspots()
        firms_cache.set(cache_key, result, ttl=60)  # Cache mock for 1 min
        return result

    today = datetime.utcnow().strftime("%Y-%m-%d")

    for source in FIRMS_SOURCES:
        nigeria_bbox = (
            f"{NIGERIA_BOUNDS['min_lon']},"
            f"{NIGERIA_BOUNDS['min_lat']},"
            f"{NIGERIA_BOUNDS['max_lon']},"
            f"{NIGERIA_BOUNDS['max_lat']}"
        )

        url_bbox = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/{nigeria_bbox}/{days}/{today}"
        response = _try_firms_request(url_bbox)
        if response is not None:
            print(f"[FIRMS] ✓ Success with bbox URL: {source}")
            result = _parse_csv_to_geojson(response.text, filter_nigeria=False)
            if result["features"]:
                firms_cache.set(cache_key, result)
                return result

        url_world = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/world/{days}/{today}"
        response = _try_firms_request(url_world)
        if response is not None:
            print(f"[FIRMS] ✓ Success with world URL: {source}")
            result = _parse_csv_to_geojson(response.text, filter_nigeria=True)
            if result["features"]:
                firms_cache.set(cache_key, result)
                return result

        url_no_date = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/{nigeria_bbox}/{days}"
        response = _try_firms_request(url_no_date)
        if response is not None:
            print(f"[FIRMS] ✓ Success with no-date URL: {source}")
            result = _parse_csv_to_geojson(response.text, filter_nigeria=False)
            if result["features"]:
                firms_cache.set(cache_key, result)
                return result

    print(f"\n[FIRMS] All attempts failed. Falling back to mock data.\n")
    result = _mock_hotspots()
    firms_cache.set(cache_key, result, ttl=60)
    return result


def _try_firms_request(url: str) -> requests.Response | None:
    try:
        print(f"[FIRMS] Trying: {url}")
        response = requests.get(url, timeout=30)
        print(f"[FIRMS] Status: {response.status_code}")

        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower() or response.text.strip().startswith("<!"):
                print(f"[FIRMS] Got HTML instead of CSV — skipping.")
                return None
            if response.text.strip():
                first_line = response.text.strip().split("\n")[0]
                if "latitude" in first_line.lower() or "," in first_line:
                    return response
                else:
                    print(f"[FIRMS] Response doesn't look like CSV: {first_line[:100]}")
                    return None
            else:
                print(f"[FIRMS] Empty response body.")
                return None
        else:
            print(f"[FIRMS] Non-200: {response.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        print(f"[FIRMS] Timeout.")
        return None
    except requests.exceptions.ConnectionError:
        print(f"[FIRMS] Connection error.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[FIRMS] Request failed: {e}")
        return None


def _parse_csv_to_geojson(csv_text: str, filter_nigeria: bool = False) -> dict:
    features = []

    try:
        reader = csv.DictReader(io.StringIO(csv_text))

        if reader.fieldnames:
            print(f"[FIRMS] CSV columns: {list(reader.fieldnames)}")

        for row in reader:
            try:
                lat = float(row.get("latitude", 0))
                lon = float(row.get("longitude", 0))

                if filter_nigeria and not _is_in_nigeria(lat, lon):
                    continue

                brightness = 0.0
                for field in ("bright_ti4", "bright_ti5", "brightness", "bright"):
                    val = row.get(field)
                    if val:
                        try:
                            brightness = float(val)
                            break
                        except ValueError:
                            continue

                confidence = str(row.get("confidence", "N")).strip().upper()
                acq_date = row.get("acq_date", "")
                acq_time = row.get("acq_time", "")
                frp = str(row.get("frp", "0"))
                daynight = row.get("daynight", "").upper()
                satellite = row.get("satellite", "")

                if confidence in ("HIGH",):
                    confidence = "H"
                elif confidence in ("NOMINAL", "NORMAL"):
                    confidence = "N"
                elif confidence in ("LOW",):
                    confidence = "L"

                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat],
                    },
                    "properties": {
                        "brightness": brightness,
                        "confidence": confidence,
                        "acq_date": acq_date,
                        "acq_time": acq_time,
                        "frp": frp,
                        "daynight": daynight,
                        "satellite": satellite,
                        "red_zone": _get_red_zone(lat, lon),
                        "source": "VIIRS_SNPP_NRT",
                    },
                }
                features.append(feature)
            except (ValueError, KeyError, TypeError) as e:
                print(f"[FIRMS] Skipping malformed row: {e}")
                continue

    except csv.Error as e:
        print(f"[FIRMS] CSV parsing error: {e}")
        print(f"[FIRMS] Raw text preview: {csv_text[:300]}")

    print(f"[FIRMS] Parsed {len(features)} features for Nigeria.")

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "NASA FIRMS",
            "sensor": "VIIRS SNPP NRT",
        },
    }


def _mock_hotspots() -> dict:
    mock_points = [
        (12.0, 8.5, "H", "2026-04-14", "0130", "Northwest Corridor"),
        (11.5, 13.2, "H", "2026-04-14", "0145", "Northeast Corridor"),
        (13.1, 5.8, "N", "2026-04-14", "0200", "Northwest Corridor"),
        (10.2, 12.8, "H", "2026-04-14", "0210", "Northeast Corridor"),
        (9.5, 6.3, "L", "2026-04-14", "0220", "North Central"),
        (12.7, 7.1, "N", "2026-04-14", "0235", "Northwest Corridor"),
        (11.9, 14.4, "H", "2026-04-14", "0250", "Northeast Corridor"),
        (8.3, 4.5, "L", "2026-04-14", "0305", "Other"),
    ]

    features = []
    for lat, lon, conf, date, time_, zone in mock_points:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "brightness": 320.0 if conf == "H" else 305.0,
                    "confidence": conf,
                    "acq_date": date,
                    "acq_time": time_,
                    "frp": "25.4" if conf == "H" else "10.1",
                    "daynight": "N",
                    "satellite": "MOCK",
                    "red_zone": zone,
                    "source": "MOCK_DATA",
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "MOCK DATA — add NASA_FIRMS_API_KEY to .env for live data",
            "sensor": "VIIRS SNPP NRT",
        },
    }