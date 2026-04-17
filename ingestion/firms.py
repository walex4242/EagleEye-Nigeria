"""
firms.py
─────────
Fetches thermal hotspot data from NASA FIRMS API with caching.
Handles the NRT API's 1–5 day limit by chunking longer requests
into multiple 5-day windows and deduplicating results.
"""

import os
import requests
import csv
import io
import traceback
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Set
from utils.geocoding import enrich_features_with_location, quick_label

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ingestion.cache import firms_cache

FIRMS_API_KEY = os.getenv("NASA_FIRMS_API_KEY", "")
FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# NASA FIRMS NRT API hard limit
FIRMS_MAX_DAYS_NRT = 5

NIGERIA_BOUNDS = {
    "min_lat": 4.0,
    "max_lat": 14.0,
    "min_lon": 2.7,
    "max_lon": 15.0,
}

RED_ZONES = [
    {
        "name": "Northwest Corridor",
        "min_lat": 11.0, "max_lat": 14.0,
        "min_lon": 4.0, "max_lon": 9.0,
    },
    {
        "name": "Northeast Corridor",
        "min_lat": 10.0, "max_lat": 14.0,
        "min_lon": 11.0, "max_lon": 15.0,
    },
    {
        "name": "North Central",
        "min_lat": 8.0, "max_lat": 11.0,
        "min_lon": 5.0, "max_lon": 10.0,
    },
]

FIRMS_SOURCES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "MODIS_NRT",
]


# ── Geo helpers ───────────────────────────────────────────────

def _get_red_zone(lat: float, lon: float) -> str:
    """Return the name of the red zone a point falls into, or 'Other'."""
    for zone in RED_ZONES:
        if (
            zone["min_lat"] <= lat <= zone["max_lat"]
            and zone["min_lon"] <= lon <= zone["max_lon"]
        ):
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


def _nigeria_bbox_str() -> str:
    """Return the Nigeria bounding box as a comma-separated string."""
    return (
        f"{NIGERIA_BOUNDS['min_lon']},"
        f"{NIGERIA_BOUNDS['min_lat']},"
        f"{NIGERIA_BOUNDS['max_lon']},"
        f"{NIGERIA_BOUNDS['max_lat']}"
    )


# ── HTTP request helper ──────────────────────────────────────

def _try_firms_request(url: str) -> Optional[requests.Response]:
    """
    Attempt a single FIRMS API request.
    Returns the Response on success, None on any failure.
    """
    try:
        print(f"[FIRMS] Trying: {url}")
        response = requests.get(url, timeout=30)
        print(f"[FIRMS] Status: {response.status_code}")

        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower() or response.text.strip().startswith("<!"):
                print("[FIRMS] Got HTML instead of CSV — skipping.")
                return None
            if response.text.strip():
                first_line = response.text.strip().split("\n")[0]
                if "latitude" in first_line.lower() or "," in first_line:
                    return response
                else:
                    print(f"[FIRMS] Response doesn't look like CSV: {first_line[:100]}")
                    return None
            else:
                print("[FIRMS] Empty response body.")
                return None
        else:
            print(f"[FIRMS] Non-200: {response.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        print("[FIRMS] Timeout.")
        return None
    except requests.exceptions.ConnectionError:
        print("[FIRMS] Connection error.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[FIRMS] Request failed: {e}")
        return None


# ── Single-window fetch (1–5 days) ───────────────────────────

def _fetch_single_window(
    days: int,
    end_date: Optional[str] = None,
    country: str = "NGA",
) -> Optional[Dict]:
    """
    Fetch hotspots for a single window of 1–5 days ending on end_date.
    Tries multiple sources and URL patterns.
    Returns a parsed GeoJSON dict or None on failure.
    """
    clamped_days = min(max(days, 1), FIRMS_MAX_DAYS_NRT)
    if end_date is None:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")

    nigeria_bbox = _nigeria_bbox_str()

    for source in FIRMS_SOURCES:
        # Try 1: bbox + date
        url = (
            f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/"
            f"{nigeria_bbox}/{clamped_days}/{end_date}"
        )
        response = _try_firms_request(url)
        if response is not None:
            print(f"[FIRMS] ✓ Success with bbox URL: {source}")
            result = _parse_csv_to_geojson(
                response.text, filter_nigeria=False, source_name=source,
            )
            if result["features"]:
                return result

        # Try 2: world + date
        url = (
            f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/"
            f"world/{clamped_days}/{end_date}"
        )
        response = _try_firms_request(url)
        if response is not None:
            print(f"[FIRMS] ✓ Success with world URL: {source}")
            result = _parse_csv_to_geojson(
                response.text, filter_nigeria=True, source_name=source,
            )
            if result["features"]:
                return result

        # Try 3: bbox without date
        url = (
            f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/"
            f"{nigeria_bbox}/{clamped_days}"
        )
        response = _try_firms_request(url)
        if response is not None:
            print(f"[FIRMS] ✓ Success with no-date URL: {source}")
            result = _parse_csv_to_geojson(
                response.text, filter_nigeria=False, source_name=source,
            )
            if result["features"]:
                return result

    return None


# ── Multi-window fetch (>5 days) ─────────────────────────────

def _fetch_chunked(
    days: int,
    country: str = "NGA",
) -> Optional[Dict]:
    """
    Fetch hotspots for more than 5 days by splitting into
    multiple 5-day windows and deduplicating the results.
    """
    print(
        f"[FIRMS] Requested {days} days (NRT limit is {FIRMS_MAX_DAYS_NRT}) "
        f"— chunking into windows"
    )

    all_features: List[Dict] = []
    end_dt = datetime.utcnow()
    remaining = days
    chunk_num = 0

    while remaining > 0:
        chunk_days = min(remaining, FIRMS_MAX_DAYS_NRT)
        chunk_end = end_dt.strftime("%Y-%m-%d")
        chunk_num += 1

        print(
            f"[FIRMS]   Chunk {chunk_num}: {chunk_days} days ending {chunk_end} "
            f"(remaining={remaining})"
        )

        result = _fetch_single_window(
            days=chunk_days,
            end_date=chunk_end,
            country=country,
        )

        if result is not None and result.get("features"):
            all_features.extend(result["features"])
            print(
                f"[FIRMS]   Chunk {chunk_num}: got {len(result['features'])} features"
            )
        else:
            print(f"[FIRMS]   Chunk {chunk_num}: no features returned")

        # Move the window backward
        end_dt -= timedelta(days=chunk_days)
        remaining -= chunk_days

    # ── Deduplicate by (lat, lon, acq_date, acq_time) ─────
    seen: Set[Tuple] = set()
    unique_features: List[Dict] = []

    for f in all_features:
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        dedup_key = (
            round(coords[1], 4),   # lat
            round(coords[0], 4),   # lon
            props.get("acq_date", ""),
            props.get("acq_time", ""),
        )

        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_features.append(f)

    duplicates_removed = len(all_features) - len(unique_features)

    print(
        f"[FIRMS] Chunked fetch complete: {len(unique_features)} unique features "
        f"from {chunk_num} chunks ({duplicates_removed} duplicates removed)"
    )

    if not unique_features:
        return None

    return {
        "type": "FeatureCollection",
        "features": unique_features,
        "metadata": {
            "count": len(unique_features),
            "source": "NASA FIRMS",
            "sensor": "VIIRS SNPP NRT",
            "days_requested": days,
            "chunks_used": chunk_num,
            "duplicates_removed": duplicates_removed,
            "fetch_method": "chunked",
        },
    }


# ── Public entry point ────────────────────────────────────────

def fetch_hotspots(days: int = 1, country: str = "NGA") -> Dict:
    """
    Fetch thermal hotspot data from NASA FIRMS API.
    Results are enriched with location names and cached.
    """
    days = max(1, min(days, 90))

    cache_key = f"firms_{country}_{days}"
    cached = firms_cache.get(cache_key)
    if cached is not None:
        count = cached.get("metadata", {}).get("count", len(cached.get("features", [])))
        print(f"[FIRMS] ✓ Cache hit for {cache_key} ({count} features)")
        return cached

    print(f"[FIRMS] Cache miss for {cache_key} — fetching from API...")

    if not _validate_api_key(FIRMS_API_KEY):
        print("[FIRMS] No valid NASA_FIRMS_API_KEY found — returning mock data.")
        result = _mock_hotspots(days=days)
        result = _enrich_result(result)                    # ← ADD THIS
        firms_cache.set(cache_key, result, ttl=60)
        return result

    result = None

    if days <= FIRMS_MAX_DAYS_NRT:
        result = _fetch_single_window(
            days=days,
            end_date=datetime.utcnow().strftime("%Y-%m-%d"),
            country=country,
        )
    else:
        result = _fetch_chunked(days=days, country=country)

    if result is not None and result.get("features"):
        result.setdefault("metadata", {})
        result["metadata"]["count"] = len(result["features"])
        result["metadata"]["days_requested"] = days

        # ── ENRICH WITH LOCATION DATA ──                   # ← ADD THIS BLOCK
        result = _enrich_result(result)

        cache_ttl = 300 if days <= 5 else 600
        firms_cache.set(cache_key, result, ttl=cache_ttl)

        print(
            f"[FIRMS] ✓ Final result: {len(result['features'])} features "
            f"for {days} day(s), cached for {cache_ttl}s"
        )
        return result

    print(f"\n[FIRMS] All attempts failed for {days} day(s). Falling back to mock data.\n")
    result = _mock_hotspots(days=days)
    result = _enrich_result(result)                        # ← ADD THIS
    firms_cache.set(cache_key, result, ttl=60)
    return result


# ── ADD THIS NEW HELPER FUNCTION ──

def _enrich_result(result: Dict) -> Dict:
    """Enrich all features with location names."""
    try:
        enriched = enrich_features_with_location(
            result,
            use_nominatim=True,
            max_nominatim_calls=100,
        )
        return enriched
    except Exception as e:
        print(f"[FIRMS] ⚠ Location enrichment failed: {e} — returning raw data")
        return result

# ── CSV parsing ───────────────────────────────────────────────

def _parse_csv_to_geojson(
    csv_text: str,
    filter_nigeria: bool = False,
    source_name: str = "VIIRS_SNPP_NRT",
) -> Dict:
    """Parse FIRMS CSV response into a GeoJSON FeatureCollection."""
    features: List[Dict] = []

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

                # Extract brightness from whichever column is available
                brightness = 0.0
                for field_name in ("bright_ti4", "bright_ti5", "brightness", "bright"):
                    val = row.get(field_name)
                    if val:
                        try:
                            brightness = float(val)
                            break
                        except ValueError:
                            continue

                # Normalize confidence
                confidence = str(row.get("confidence", "N")).strip().upper()
                if confidence in ("HIGH",):
                    confidence = "H"
                elif confidence in ("NOMINAL", "NORMAL"):
                    confidence = "N"
                elif confidence in ("LOW",):
                    confidence = "L"

                acq_date = row.get("acq_date", "")
                acq_time = row.get("acq_time", "")
                frp = str(row.get("frp", "0"))
                daynight = row.get("daynight", "").upper()
                satellite = row.get("satellite", "")

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
                        "source": source_name,
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
            "sensor": source_name,
        },
    }


# ── Mock data fallback ───────────────────────────────────────

def _mock_hotspots(days: int = 1) -> Dict:
    """
    Generate mock hotspot data for demo/development.
    Scales the number of points based on days requested.
    """
    # Base mock points (single day)
    base_points = [
        (12.0, 8.5, "H", "Northwest Corridor", 340.2, 45.3),
        (11.5, 13.2, "H", "Northeast Corridor", 335.8, 38.7),
        (13.1, 5.8, "N", "Northwest Corridor", 312.4, 15.2),
        (10.2, 12.8, "H", "Northeast Corridor", 328.9, 32.1),
        (9.5, 6.3, "L", "North Central", 301.5, 8.4),
        (12.7, 7.1, "N", "Northwest Corridor", 318.3, 22.6),
        (11.9, 14.4, "H", "Northeast Corridor", 344.1, 52.8),
        (8.3, 4.5, "L", "Other", 298.7, 5.2),
    ]

    features: List[Dict] = []
    base_dt = datetime.utcnow()

    # Generate points for each day requested
    for day_offset in range(min(days, 30)):
        dt = base_dt - timedelta(days=day_offset)
        date_str = dt.strftime("%Y-%m-%d")

        for i, (lat, lon, conf, zone, bright, frp) in enumerate(base_points):
            # Slight positional jitter per day so they aren't identical
            if day_offset > 0:
                import hashlib
                jitter_seed = int(
                    hashlib.md5(f"{day_offset}-{i}".encode()).hexdigest()[:8],
                    16,
                )
                jitter_lat = ((jitter_seed % 100) - 50) / 1000.0
                jitter_lon = (((jitter_seed >> 8) % 100) - 50) / 1000.0
                lat += jitter_lat
                lon += jitter_lon

            hour = 1 + (i * 15) // 60
            minute = (i * 15) % 60
            time_str = f"{hour:02d}{minute:02d}"

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "brightness": bright,
                    "confidence": conf,
                    "acq_date": date_str,
                    "acq_time": time_str,
                    "frp": str(frp),
                    "daynight": "N",
                    "satellite": "MOCK",
                    "red_zone": zone,
                    "source": "MOCK_DATA",
                },
            })

    print(
        f"[FIRMS] Generated {len(features)} mock features "
        f"for {days} day(s)"
    )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": (
                "MOCK DATA — add NASA_FIRMS_API_KEY to .env for live data"
            ),
            "sensor": "VIIRS SNPP NRT",
            "days_requested": days,
            "fetch_method": "mock",
        },
    }