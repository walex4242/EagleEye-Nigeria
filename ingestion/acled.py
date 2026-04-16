"""
acled.py
─────────
Fetches conflict event data from ACLED API using OAuth authentication.
Used to correlate satellite thermal detections with ground-truth conflict events.

ACLED API docs: https://acleddata.com/acleddatanew/wp-content/uploads/dlm_uploads/2024/01/API-Guide-V3.pdf
New OAuth flow: https://acleddata.com/api-documentation/

Authentication flow:
  1. POST credentials to /oauth/token → get access_token (24h)
  2. Use Bearer token in Authorization header for data requests
"""

from __future__ import annotations
import os
import time
import requests
import traceback
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ACLED_EMAIL = os.getenv("ACLED_EMAIL", "")
ACLED_PASSWORD = os.getenv("ACLED_PASSWORD", "")

ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_BASE = "https://acleddata.com/api/acled/read"

# Nigeria ISO code
NIGERIA_ISO = 566

# Cache the token
_token_cache = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": 0,
}


def _get_access_token() -> str | None:
    """
    Authenticate with ACLED OAuth and return an access token.
    Caches the token and refreshes when expired.
    """
    now = time.time()

    # Return cached token if still valid (with 5-min buffer)
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 300:
        return _token_cache["access_token"]

    # Try refresh token first
    if _token_cache["refresh_token"]:
        token = _refresh_token(_token_cache["refresh_token"])
        if token:
            return token

    # Full authentication
    if not ACLED_EMAIL or not ACLED_PASSWORD:
        print("[ACLED] No credentials found. Set ACLED_EMAIL and ACLED_PASSWORD in .env")
        return None

    try:
        print("[ACLED] Authenticating with OAuth...")
        response = requests.post(
            ACLED_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "username": ACLED_EMAIL,
                "password": ACLED_PASSWORD,
                "grant_type": "password",
                "client_id": "acled",
            },
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            _token_cache["access_token"] = data["access_token"]
            _token_cache["refresh_token"] = data.get("refresh_token")
            _token_cache["expires_at"] = now + data.get("expires_in", 86400)
            print(f"[ACLED] ✓ Authenticated. Token expires in {data.get('expires_in', 86400)}s")
            return data["access_token"]
        else:
            print(f"[ACLED] ✗ Auth failed: {response.status_code} — {response.text[:300]}")
            return None

    except Exception as e:
        print(f"[ACLED] ✗ Auth error: {e}")
        traceback.print_exc()
        return None


def _refresh_token(refresh_token: str) -> str | None:
    """Use refresh token to get a new access token."""
    try:
        print("[ACLED] Refreshing token...")
        response = requests.post(
            ACLED_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "client_id": "acled",
            },
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            _token_cache["access_token"] = data["access_token"]
            _token_cache["refresh_token"] = data.get("refresh_token", refresh_token)
            _token_cache["expires_at"] = time.time() + data.get("expires_in", 86400)
            print("[ACLED] ✓ Token refreshed.")
            return data["access_token"]
        else:
            print(f"[ACLED] ✗ Refresh failed: {response.status_code}")
            _token_cache["refresh_token"] = None
            return None

    except Exception as e:
        print(f"[ACLED] ✗ Refresh error: {e}")
        return None


def fetch_acled_events(
    days: int = 30,
    country: str = "Nigeria",
    event_types: list[str] | None = None,
    limit: int = 5000,
) -> dict:
    """
    Fetch conflict events from ACLED for Nigeria.

    Args:
        days: Number of past days to query.
        country: Country name.
        event_types: Filter by event types (e.g., ['Battles', 'Violence against civilians']).
        limit: Maximum number of events to return.

    Returns:
        GeoJSON FeatureCollection of conflict events.
    """
    token = _get_access_token()
    if not token:
        print("[ACLED] No token — returning mock data.")
        return _mock_acled_events()

    # Date range
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "country": country,
        "event_date": f"{start_date}|{end_date}",
        "event_date_where": "BETWEEN",
        "fields": "event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2|"
                  "admin1|admin2|location|latitude|longitude|fatalities|notes|source",
        "limit": limit,
    }

    # Add event type filter if specified
    if event_types:
        params["event_type"] = ":OR:event_type=".join(event_types)

    try:
        print(f"[ACLED] Fetching events: {country}, last {days} days...")
        response = requests.get(
            f"{ACLED_API_BASE}?_format=json",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()

            if data.get("status") == 200:
                events = data.get("data", [])
                print(f"[ACLED] ✓ Fetched {len(events)} events.")
                return _events_to_geojson(events)
            else:
                print(f"[ACLED] API returned status: {data.get('status')}")
                print(f"[ACLED] Message: {data.get('message', 'Unknown')}")
                return _mock_acled_events()
        elif response.status_code == 401:
            print("[ACLED] Token expired. Clearing cache.")
            _token_cache["access_token"] = None
            _token_cache["expires_at"] = 0
            # Retry once
            return fetch_acled_events(days, country, event_types, limit)
        else:
            print(f"[ACLED] ✗ Request failed: {response.status_code} — {response.text[:300]}")
            return _mock_acled_events()

    except requests.exceptions.Timeout:
        print("[ACLED] Request timed out.")
        return _mock_acled_events()
    except Exception as e:
        print(f"[ACLED] ✗ Error: {e}")
        traceback.print_exc()
        return _mock_acled_events()


def _events_to_geojson(events: list[dict]) -> dict:
    """Convert ACLED event records to GeoJSON FeatureCollection."""
    features = []

    for event in events:
        try:
            lat = float(event.get("latitude", 0))
            lon = float(event.get("longitude", 0))

            if lat == 0 and lon == 0:
                continue

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "event_id": event.get("event_id_cnty", ""),
                    "event_date": event.get("event_date", ""),
                    "event_type": event.get("event_type", ""),
                    "sub_event_type": event.get("sub_event_type", ""),
                    "actor1": event.get("actor1", ""),
                    "actor2": event.get("actor2", ""),
                    "admin1": event.get("admin1", ""),
                    "admin2": event.get("admin2", ""),
                    "location": event.get("location", ""),
                    "fatalities": int(event.get("fatalities", 0)),
                    "notes": event.get("notes", ""),
                    "source": event.get("source", ""),
                    "data_source": "ACLED",
                },
            }
            features.append(feature)
        except (ValueError, KeyError, TypeError) as e:
            print(f"[ACLED] Skipping malformed event: {e}")
            continue

    # Sort by date descending
    features.sort(key=lambda f: f["properties"].get("event_date", ""), reverse=True)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "ACLED",
            "dataset": "Armed Conflict Location & Event Data",
        },
    }


def correlate_with_hotspots(
    hotspots_geojson: dict,
    acled_geojson: dict,
    radius_km: float = 25.0,
) -> dict:
    """
    Correlate FIRMS thermal hotspots with ACLED conflict events.
    For each hotspot, find nearby ACLED events within radius_km.

    Returns enriched hotspot GeoJSON with 'nearby_events' count and details.
    """
    from math import radians, cos, sin, asin, sqrt

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
        return R * 2 * asin(sqrt(a))

    acled_points = []
    for f in acled_geojson.get("features", []):
        coords = f.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            acled_points.append({
                "lon": coords[0],
                "lat": coords[1],
                "props": f.get("properties", {}),
            })

    enriched_features = []
    total_correlations = 0

    for feature in hotspots_geojson.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            enriched_features.append(feature)
            continue

        h_lon, h_lat = coords[0], coords[1]
        nearby = []

        for ap in acled_points:
            dist = haversine(h_lat, h_lon, ap["lat"], ap["lon"])
            if dist <= radius_km:
                nearby.append({
                    "event_type": ap["props"].get("event_type", ""),
                    "event_date": ap["props"].get("event_date", ""),
                    "fatalities": ap["props"].get("fatalities", 0),
                    "location": ap["props"].get("location", ""),
                    "distance_km": round(dist, 1),
                })

        nearby.sort(key=lambda x: x["distance_km"])

        total_fatalities = sum(e.get("fatalities", 0) for e in nearby)

        props = {
            **feature.get("properties", {}),
            "nearby_conflict_events": len(nearby),
            "nearby_fatalities": total_fatalities,
            "conflict_correlation": len(nearby) > 0,
            "nearest_events": nearby[:5],  # Top 5 nearest
        }

        if len(nearby) > 0:
            total_correlations += 1

        enriched_features.append({**feature, "properties": props})

    return {
        **hotspots_geojson,
        "features": enriched_features,
        "metadata": {
            **hotspots_geojson.get("metadata", {}),
            "acled_correlated": True,
            "correlated_hotspots": total_correlations,
            "total_acled_events": len(acled_points),
        },
    }


def _mock_acled_events() -> dict:
    """Mock ACLED data for development."""
    mock_events = [
        {
            "lat": 12.0, "lon": 7.5,
            "event_type": "Battles", "sub_event_type": "Armed clash",
            "event_date": "2026-04-10", "fatalities": 5,
            "actor1": "Military Forces of Nigeria",
            "actor2": "Boko Haram",
            "admin1": "Zamfara", "location": "Anka",
        },
        {
            "lat": 11.8, "lon": 13.1,
            "event_type": "Violence against civilians", "sub_event_type": "Attack",
            "event_date": "2026-04-12", "fatalities": 12,
            "actor1": "ISWAP",
            "actor2": "Civilians",
            "admin1": "Borno", "location": "Maiduguri",
        },
        {
            "lat": 10.5, "lon": 7.4,
            "event_type": "Battles", "sub_event_type": "Armed clash",
            "event_date": "2026-04-08", "fatalities": 3,
            "actor1": "Fulani Ethnic Militia",
            "actor2": "Military Forces of Nigeria",
            "admin1": "Kaduna", "location": "Birnin Gwari",
        },
        {
            "lat": 9.8, "lon": 8.9,
            "event_type": "Violence against civilians", "sub_event_type": "Attack",
            "event_date": "2026-04-11", "fatalities": 8,
            "actor1": "Fulani Ethnic Militia",
            "actor2": "Civilians",
            "admin1": "Plateau", "location": "Jos South",
        },
        {
            "lat": 13.0, "lon": 5.2,
            "event_type": "Battles", "sub_event_type": "Armed clash",
            "event_date": "2026-04-13", "fatalities": 2,
            "actor1": "Military Forces of Nigeria",
            "actor2": "Bandits",
            "admin1": "Sokoto", "location": "Isa",
        },
        {
            "lat": 11.5, "lon": 12.5,
            "event_type": "Explosions/Remote violence", "sub_event_type": "Suicide bomb",
            "event_date": "2026-04-09", "fatalities": 15,
            "actor1": "Boko Haram",
            "actor2": "Civilians",
            "admin1": "Yobe", "location": "Damaturu",
        },
    ]

    features = []
    for i, e in enumerate(mock_events):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
            "properties": {
                "event_id": f"MOCK_{i+1}",
                "event_date": e["event_date"],
                "event_type": e["event_type"],
                "sub_event_type": e["sub_event_type"],
                "actor1": e["actor1"],
                "actor2": e.get("actor2", ""),
                "admin1": e["admin1"],
                "admin2": "",
                "location": e["location"],
                "fatalities": e["fatalities"],
                "notes": "Mock event for development",
                "source": "MOCK_DATA",
                "data_source": "ACLED_MOCK",
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "ACLED MOCK — set ACLED_EMAIL and ACLED_PASSWORD in .env for live data",
            "dataset": "Armed Conflict Location & Event Data (Mock)",
        },
    }