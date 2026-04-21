"""
firms.py
─────────
Fetches thermal hotspot data from NASA FIRMS API with caching.

FIRMS API Day Limits (as of 2024+):
  - Area/bbox endpoint:    max 5 days per request
  - Country endpoint:      max 10 days per request

This module respects both limits and chunks longer requests accordingly.
Includes fast geo enrichment (no external geocoding dependencies).
"""

import os
import csv
import io
import hashlib
import traceback
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple, Set

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ingestion.cache import firms_cache

FIRMS_API_KEY = os.getenv("NASA_FIRMS_API_KEY", "")

# ── FIRMS endpoints ──────────────────────────────────────────
FIRMS_COUNTRY_URL = "https://firms.modaps.eosdis.nasa.gov/api/country/csv"
FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# ── FIRMS API hard day limits ────────────────────────────────
# These are enforced server-side and CANNOT be exceeded
FIRMS_MAX_DAYS_AREA = 5       # /api/area/ endpoint limit
FIRMS_MAX_DAYS_COUNTRY = 10   # /api/country/ endpoint limit

# For chunking, use the smaller limit to guarantee all URLs work
FIRMS_CHUNK_SIZE = 5

# ── Geo Enrichment Config ─────────────────────────────────────
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

# ── Source priority list ─────────────────────────────────────
# Ordered by reliability/freshness — stop after first success
FIRMS_SOURCES = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
    "VIIRS_SNPP_SP",
    "VIIRS_NOAA20_SP",
    "MODIS_SP",
]

# ── Fast Local Region Lookup (no API calls) ──────────────────
NIGERIA_STATES = {
    "FCT Abuja":       (9.05, 7.49),
    "Lagos":           (6.52, 3.37),
    "Kano":            (12.00, 8.52),
    "Rivers":          (4.84, 6.91),
    "Oyo":             (7.85, 3.93),
    "Kaduna":          (10.52, 7.44),
    "Borno":           (11.85, 13.15),
    "Benue":           (7.34, 8.77),
    "Niger":           (9.93, 5.60),
    "Plateau":         (9.22, 9.52),
    "Adamawa":         (9.33, 12.40),
    "Bauchi":          (10.31, 9.84),
    "Taraba":          (8.00, 10.73),
    "Zamfara":         (12.17, 6.25),
    "Katsina":         (13.00, 7.60),
    "Sokoto":          (13.06, 5.24),
    "Kebbi":           (12.45, 4.20),
    "Jigawa":          (12.23, 9.56),
    "Yobe":            (12.29, 11.75),
    "Gombe":           (10.29, 11.17),
    "Nasarawa":        (8.54, 8.52),
    "Kwara":           (8.49, 4.54),
    "Kogi":            (7.73, 6.69),
    "Ogun":            (6.97, 3.39),
    "Osun":            (7.56, 4.52),
    "Ekiti":           (7.72, 5.31),
    "Ondo":            (7.10, 5.05),
    "Edo":             (6.63, 5.93),
    "Delta":           (5.70, 5.68),
    "Bayelsa":         (4.77, 6.07),
    "Anambra":         (6.21, 6.94),
    "Enugu":           (6.44, 7.50),
    "Ebonyi":          (6.26, 8.09),
    "Imo":             (5.57, 7.03),
    "Abia":            (5.45, 7.52),
    "Cross River":     (5.87, 8.60),
    "Akwa Ibom":       (5.01, 7.85),
}

LATITUDE_ZONES = [
    (12.0, 14.0, "Far North"),
    (10.0, 12.0, "North"),
    (8.0, 10.0, "North Central"),
    (6.5, 8.0, "South West / South East"),
    (4.0, 6.5, "South South"),
]


# ══════════════════════════════════════════════════════════════
#  Fast Geo Helpers (all local, no external API)
# ══════════════════════════════════════════════════════════════

def _get_red_zone(lat: float, lon: float) -> str:
    """Return the name of the red zone a point falls into, or 'Other'."""
    for zone in RED_ZONES:
        if (
            zone["min_lat"] <= lat <= zone["max_lat"]
            and zone["min_lon"] <= lon <= zone["max_lon"]
        ):
            return zone["name"]
    return "Other"


def _get_nearest_state(lat: float, lon: float) -> str:
    """Find the nearest Nigerian state by coordinate distance (instant)."""
    best_state = "Unknown"
    best_dist = float("inf")

    for state_name, (s_lat, s_lon) in NIGERIA_STATES.items():
        dist = (lat - s_lat) ** 2 + (lon - s_lon) ** 2
        if dist < best_dist:
            best_dist = dist
            best_state = state_name

    # Only return if within ~1.5 degrees (~170km)
    if best_dist > 2.25:
        return "Unknown"
    return best_state


def _get_geo_zone(lat: float) -> str:
    """Get broad geo zone from latitude (instant)."""
    for min_lat, max_lat, zone_name in LATITUDE_ZONES:
        if min_lat <= lat <= max_lat:
            return zone_name
    return "Nigeria"


def _is_in_nigeria(lat: float, lon: float) -> bool:
    return (
        NIGERIA_BOUNDS["min_lat"] <= lat <= NIGERIA_BOUNDS["max_lat"]
        and NIGERIA_BOUNDS["min_lon"] <= lon <= NIGERIA_BOUNDS["max_lon"]
    )


def _validate_api_key(key: str) -> bool:
    return bool(key and len(key) >= 10)


def _nigeria_bbox_str() -> str:
    """Return W,S,E,N bbox string for Nigeria."""
    return (
        f"{NIGERIA_BOUNDS['min_lon']},"
        f"{NIGERIA_BOUNDS['min_lat']},"
        f"{NIGERIA_BOUNDS['max_lon']},"
        f"{NIGERIA_BOUNDS['max_lat']}"
    )


def _get_safe_end_date() -> str:
    """
    Return a safe end date for the FIRMS API.
    Uses yesterday UTC to guarantee data availability
    (today's data may not be processed yet).
    """
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
#  Fast Enrichment (all local, no external API)
# ══════════════════════════════════════════════════════════════

def _enrich_result(result: Dict) -> Dict:
    """
    Enrich all features with location data using local lookups only.
    No external API calls — runs instantly.
    """
    features = result.get("features", [])
    if not features:
        return result

    total = len(features)
    start_time = datetime.now(timezone.utc)

    for f in features:
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        lon = coords[0] if len(coords) > 0 else 0
        lat = coords[1] if len(coords) > 1 else 0

        if lat and lon:
            props["state"] = _get_nearest_state(lat, lon)
            props["geo_zone"] = _get_geo_zone(lat)
            props["latitude"] = lat
            props["longitude"] = lon
            props["geo_source"] = "local_lookup"

            if not props.get("red_zone"):
                props["red_zone"] = _get_red_zone(lat, lon)

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"[GEO] ✓ Local enrichment: {total} features in {elapsed:.3f}s")

    result["features"] = features
    return result


# ══════════════════════════════════════════════════════════════
#  HTTP Request Helper
# ══════════════════════════════════════════════════════════════

def _try_firms_request(url: str) -> Optional[requests.Response]:
    """
    Attempt a single FIRMS API request.
    Returns the Response on success, None on any failure.
    """
    try:
        print(f"[FIRMS] Trying: {url}")
        response = requests.get(url, timeout=45)
        print(f"[FIRMS] Status: {response.status_code}")

        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            body = response.text.strip()

            if not body:
                print("[FIRMS] Empty response body.")
                return None

            if "html" in content_type.lower() or body.startswith("<!"):
                print("[FIRMS] Got HTML instead of CSV — skipping.")
                return None

            lines = body.split("\n")
            first_line = lines[0] if lines else ""

            if "latitude" not in first_line.lower():
                print(
                    f"[FIRMS] Response doesn't look like FIRMS CSV: "
                    f"{first_line[:120]}"
                )
                return None

            data_rows = len(lines) - 1
            print(f"[FIRMS] CSV has {data_rows} data row(s)")

            if data_rows < 1:
                print("[FIRMS] CSV has headers but no data rows.")
                return response  # Valid empty — caller sees 0 features

            return response
        else:
            print(f"[FIRMS] Non-200 status: {response.status_code}")
            preview = response.text[:300] if response.text else "(empty)"
            print(f"[FIRMS] Response preview: {preview}")
            return None

    except requests.exceptions.Timeout:
        print("[FIRMS] Timeout (45s).")
        return None
    except requests.exceptions.ConnectionError:
        print("[FIRMS] Connection error.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[FIRMS] Request failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  URL Builders (FIXED — respects per-endpoint day limits)
# ══════════════════════════════════════════════════════════════

def _build_country_urls(
    source: str, days: int, end_date: Optional[str], country: str
) -> List[str]:
    """
    Build country endpoint URLs.
    Country endpoint supports up to 10 days.
    """
    clamped = min(days, FIRMS_MAX_DAYS_COUNTRY)
    urls = []

    if end_date:
        urls.append(
            f"{FIRMS_COUNTRY_URL}/{FIRMS_API_KEY}/{source}"
            f"/{country}/{clamped}/{end_date}"
        )
    # Without date (API uses latest available)
    urls.append(
        f"{FIRMS_COUNTRY_URL}/{FIRMS_API_KEY}/{source}"
        f"/{country}/{clamped}"
    )

    return urls


def _build_area_urls(
    source: str, days: int, end_date: Optional[str]
) -> List[str]:
    """
    Build area/bbox endpoint URLs.
    Area endpoint supports up to 5 days ONLY.
    """
    clamped = min(days, FIRMS_MAX_DAYS_AREA)
    bbox = _nigeria_bbox_str()
    urls = []

    if end_date:
        urls.append(
            f"{FIRMS_AREA_URL}/{FIRMS_API_KEY}/{source}"
            f"/{bbox}/{clamped}/{end_date}"
        )
    # Without date
    urls.append(
        f"{FIRMS_AREA_URL}/{FIRMS_API_KEY}/{source}"
        f"/{bbox}/{clamped}"
    )

    return urls


def _build_all_urls(
    source: str, days: int, end_date: Optional[str], country: str
) -> List[Tuple[str, bool]]:
    """
    Build a prioritized list of (url, needs_nigeria_filter) tuples.
    Country endpoint first (higher day limit, pre-filtered),
    then area endpoint as fallback.
    """
    urls: List[Tuple[str, bool]] = []

    # Country endpoint — no Nigeria filter needed (already filtered)
    for url in _build_country_urls(source, days, end_date, country):
        urls.append((url, False))

    # Area endpoint — may need Nigeria filter if bbox is wider
    for url in _build_area_urls(source, days, end_date):
        urls.append((url, False))  # Our bbox IS Nigeria, no extra filter

    return urls


# ══════════════════════════════════════════════════════════════
#  Single-Window Fetch (respects day limits)
# ══════════════════════════════════════════════════════════════

def _fetch_single_window(
    days: int,
    end_date: Optional[str] = None,
    country: str = "NGA",
) -> Optional[Dict]:
    """
    Fetch hotspots for a single window.
    Automatically clamps days to API limits per endpoint type.
    Tries multiple sources and URL patterns.
    """
    if end_date is None:
        end_date = _get_safe_end_date()

    # Clamp to the maximum either endpoint can handle
    effective_days = min(max(days, 1), FIRMS_MAX_DAYS_COUNTRY)

    print(f"[FIRMS] Fetching {effective_days} day(s), end_date={end_date}")

    for source in FIRMS_SOURCES:
        url_pairs = _build_all_urls(source, effective_days, end_date, country)

        for url, needs_filter in url_pairs:
            response = _try_firms_request(url)
            if response is None:
                continue

            result = _parse_csv_to_geojson(
                response.text,
                filter_nigeria=needs_filter,
                source_name=source,
            )

            if result["features"]:
                print(
                    f"[FIRMS] ✓ Got {len(result['features'])} features "
                    f"from {source}"
                )
                return result

    # ── Last resort: each source, country endpoint, no date ──
    print(
        "[FIRMS] All dated requests returned 0 features. "
        "Trying without date..."
    )
    for source in FIRMS_SOURCES:
        # Country endpoint, clamped days, no date
        clamped = min(effective_days, FIRMS_MAX_DAYS_COUNTRY)
        url = (
            f"{FIRMS_COUNTRY_URL}/{FIRMS_API_KEY}/{source}"
            f"/{country}/{clamped}"
        )
        response = _try_firms_request(url)
        if response is not None:
            result = _parse_csv_to_geojson(
                response.text,
                filter_nigeria=False,
                source_name=source,
            )
            if result["features"]:
                print(
                    f"[FIRMS] ✓ Got {len(result['features'])} features "
                    f"from {source} (no-date fallback)"
                )
                return result

    return None


# ══════════════════════════════════════════════════════════════
#  Multi-Window Chunked Fetch (FIXED chunk size)
# ══════════════════════════════════════════════════════════════

def _fetch_chunked(
    days: int,
    country: str = "NGA",
) -> Optional[Dict]:
    """
    Fetch hotspots for more than 5 days by splitting into
    FIRMS_CHUNK_SIZE-day windows (default 5) and deduplicating.

    Uses 5-day chunks because that's the limit shared by both
    area and country endpoints (country allows 10, but 5 is safer
    and gives us access to both endpoint types as fallback).
    """
    chunk_size = FIRMS_CHUNK_SIZE
    num_chunks = (days + chunk_size - 1) // chunk_size

    print(
        f"[FIRMS] Requested {days} days → "
        f"{num_chunks} chunk(s) of ≤{chunk_size} days each"
    )

    all_features: List[Dict] = []
    end_dt = datetime.now(timezone.utc) - timedelta(days=1)  # yesterday
    remaining = days
    chunk_num = 0

    while remaining > 0:
        chunk_days = min(remaining, chunk_size)
        chunk_end = end_dt.strftime("%Y-%m-%d")
        chunk_num += 1

        print(
            f"[FIRMS]   Chunk {chunk_num}/{num_chunks}: "
            f"{chunk_days} days ending {chunk_end} "
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
                f"[FIRMS]   Chunk {chunk_num}: "
                f"got {len(result['features'])} features"
            )
        else:
            print(f"[FIRMS]   Chunk {chunk_num}: no features returned")

        end_dt -= timedelta(days=chunk_days)
        remaining -= chunk_days

    # ── Deduplicate by (lat, lon, acq_date, acq_time) ─────
    seen: Set[Tuple] = set()
    unique_features: List[Dict] = []

    for f in all_features:
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        dedup_key = (
            round(coords[1], 4),
            round(coords[0], 4),
            props.get("acq_date", ""),
            props.get("acq_time", ""),
        )
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_features.append(f)

    duplicates_removed = len(all_features) - len(unique_features)

    print(
        f"[FIRMS] Chunked fetch complete: {len(unique_features)} unique "
        f"features from {chunk_num} chunks "
        f"({duplicates_removed} duplicates removed)"
    )

    if not unique_features:
        return None

    return {
        "type": "FeatureCollection",
        "features": unique_features,
        "metadata": {
            "count": len(unique_features),
            "source": "NASA FIRMS",
            "sensor": "Multi-source",
            "days_requested": days,
            "chunks_used": chunk_num,
            "duplicates_removed": duplicates_removed,
            "fetch_method": "chunked",
        },
    }


# ══════════════════════════════════════════════════════════════
#  Public Entry Point
# ══════════════════════════════════════════════════════════════

def fetch_hotspots(days: int = 2, country: str = "NGA") -> Dict:
    """
    Fetch thermal hotspot data from NASA FIRMS API.
    Results are enriched with location names and cached.

    Day handling:
      - 1–5 days:   single request (works with both endpoints)
      - 6–10 days:  single request via country endpoint, or 2 chunks
      - 11–90 days: chunked into 5-day windows automatically

    Performance:
      - All geo enrichment is local (0 external API calls)
      - Enrichment runs in <0.01s for hundreds of features
    """
    days = max(1, min(days, 90))

    cache_key = f"firms_{country}_{days}"
    cached = firms_cache.get(cache_key)
    if cached is not None:
        count = cached.get("metadata", {}).get(
            "count", len(cached.get("features", []))
        )
        print(f"[FIRMS] ✓ Cache hit for {cache_key} ({count} features)")
        return cached
    
     # ── Deduplication: prevent concurrent identical API calls ──
    status = firms_cache.wait_or_claim(cache_key, timeout=50.0)

    if status == "waited":
        # Another thread just fetched this — grab from cache
        cached = firms_cache.get(cache_key)
        if cached is not None:
            print(f"[FIRMS] ✓ Dedup hit for {cache_key}")
            return cached
        # If still None, fall through and fetch ourselves

    print(f"[FIRMS] Cache miss for {cache_key} — fetching from API...")
    print(f"[FIRMS] System UTC time: {datetime.now(timezone.utc).isoformat()}")
    print(f"[FIRMS] Safe end date:   {_get_safe_end_date()}")

    if not _validate_api_key(FIRMS_API_KEY):
        print(
            "[FIRMS] ⚠ No valid NASA_FIRMS_API_KEY found "
            "— returning mock data."
        )
        result = _mock_hotspots(days=days)
        result = _enrich_result(result)
        firms_cache.set(cache_key, result, ttl=60)
        return result

    result = None

    # ── Strategy: try exact days first, then widen if empty ──
    attempts = [days]
    if days <= 2:
        attempts = [days, 3, 5]
    elif days <= 5:
        attempts = [days, 5]

    for attempt_days in attempts:
        print(f"[FIRMS] === Attempting {attempt_days}-day fetch ===")

        if attempt_days <= FIRMS_CHUNK_SIZE:
            # Single window — fits within both endpoint limits
            result = _fetch_single_window(
                days=attempt_days,
                end_date=_get_safe_end_date(),
                country=country,
            )
        else:
            # Need chunking
            result = _fetch_chunked(days=attempt_days, country=country)

        if result is not None and result.get("features"):
            result.setdefault("metadata", {})
            result["metadata"]["count"] = len(result["features"])
            result["metadata"]["days_requested"] = days
            result["metadata"]["days_fetched"] = attempt_days

            # Enrich with location data (instant, local only)
            result = _enrich_result(result)

            cache_ttl = 300 if days <= 5 else 600
            firms_cache.set(cache_key, result, ttl=cache_ttl)

            print(
                f"[FIRMS] ✓ Final result: {len(result['features'])} "
                f"features for {attempt_days} day(s), "
                f"cached for {cache_ttl}s"
            )
            return result

        print(f"[FIRMS] {attempt_days}-day fetch returned 0 features.")

    print(
        f"\n[FIRMS] ⚠ All attempts failed for {days} day(s). "
        f"Falling back to mock data.\n"
    )
    result = _mock_hotspots(days=days)
    result = _enrich_result(result)
    firms_cache.set(cache_key, result, ttl=60)
    return result


# ══════════════════════════════════════════════════════════════
#  CSV Parsing
# ══════════════════════════════════════════════════════════════

def _parse_csv_to_geojson(
    csv_text: str,
    filter_nigeria: bool = False,
    source_name: str = "VIIRS_SNPP_NRT",
) -> Dict:
    """Parse FIRMS CSV response into a GeoJSON FeatureCollection."""
    features: List[Dict] = []

    try:
        lines = csv_text.strip().split("\n")
        print(
            f"[FIRMS] CSV total lines: {len(lines)} "
            f"(1 header + {len(lines)-1} data)"
        )

        if len(lines) <= 5:
            for i, line in enumerate(lines):
                print(f"[FIRMS]   Line {i}: {line[:200]}")

        reader = csv.DictReader(io.StringIO(csv_text))

        if reader.fieldnames:
            print(f"[FIRMS] CSV columns: {list(reader.fieldnames)}")

        row_count = 0
        filtered_out = 0

        for row in reader:
            row_count += 1
            try:
                lat_str = row.get("latitude", "")
                lon_str = row.get("longitude", "")

                if not lat_str or not lon_str:
                    continue

                lat = float(lat_str)
                lon = float(lon_str)

                if filter_nigeria and not _is_in_nigeria(lat, lon):
                    filtered_out += 1
                    continue

                # Extract brightness from multiple possible columns
                brightness = 0.0
                for field_name in (
                    "bright_ti4", "bright_ti5", "brightness", "bright",
                ):
                    val = row.get(field_name)
                    if val:
                        try:
                            brightness = float(val)
                            break
                        except ValueError:
                            continue

                # Normalize confidence values
                confidence = str(row.get("confidence", "N")).strip()
                conf_upper = confidence.upper()
                if conf_upper in ("HIGH", "H"):
                    confidence = "H"
                elif conf_upper in ("NOMINAL", "NORMAL", "N"):
                    confidence = "N"
                elif conf_upper in ("LOW", "L"):
                    confidence = "L"
                else:
                    try:
                        conf_val = int(confidence)
                        if conf_val >= 80:
                            confidence = "H"
                        elif conf_val >= 30:
                            confidence = "N"
                        else:
                            confidence = "L"
                    except ValueError:
                        confidence = "N"

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
                        "latitude": lat,
                        "longitude": lon,
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

        print(
            f"[FIRMS] Parsed {len(features)} features "
            f"(read {row_count} rows, filtered out {filtered_out})"
        )

    except csv.Error as e:
        print(f"[FIRMS] CSV parsing error: {e}")
        print(f"[FIRMS] Raw text preview: {csv_text[:500]}")

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "NASA FIRMS",
            "sensor": source_name,
        },
    }


# ══════════════════════════════════════════════════════════════
#  Mock Data Fallback
# ══════════════════════════════════════════════════════════════

def _mock_hotspots(days: int = 1) -> Dict:
    """
    Generate mock hotspot data for demo/development.
    Scales the number of points based on days requested.
    """
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
    base_dt = datetime.now(timezone.utc)

    for day_offset in range(min(days, 30)):
        dt = base_dt - timedelta(days=day_offset)
        date_str = dt.strftime("%Y-%m-%d")

        for i, (lat, lon, conf, zone, bright, frp) in enumerate(base_points):
            if day_offset > 0:
                jitter_seed = int(
                    hashlib.md5(
                        f"{day_offset}-{i}".encode()
                    ).hexdigest()[:8],
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
                    "latitude": lat,
                    "longitude": lon,
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
                "MOCK DATA — add NASA_FIRMS_API_KEY to .env "
                "for live data"
            ),
            "sensor": "VIIRS SNPP NRT",
            "days_requested": days,
            "fetch_method": "mock",
        },
    }