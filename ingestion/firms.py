import os
import requests
import csv
import io
from dotenv import load_dotenv

load_dotenv()

FIRMS_API_KEY = os.getenv("NASA_FIRMS_API_KEY", "")
FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/country/csv"

# Nigeria bounding box for quick spatial filtering
NIGERIA_BOUNDS = {
    "min_lat": 4.0,
    "max_lat": 14.0,
    "min_lon": 2.7,
    "max_lon": 15.0
}

# Known red zones (Northwest / Northeast corridors)
RED_ZONES = [
    {"name": "Northwest Corridor",  "min_lat": 11.0, "max_lat": 14.0, "min_lon": 4.0,  "max_lon": 9.0},
    {"name": "Northeast Corridor",  "min_lat": 10.0, "max_lat": 14.0, "min_lon": 11.0, "max_lon": 15.0},
    {"name": "North Central",       "min_lat": 8.0,  "max_lat": 11.0, "min_lon": 5.0,  "max_lon": 10.0},
]


def _get_red_zone(lat: float, lon: float) -> str:
    """Return the red zone name if coordinates fall within one."""
    for zone in RED_ZONES:
        if (zone["min_lat"] <= lat <= zone["max_lat"] and
                zone["min_lon"] <= lon <= zone["max_lon"]):
            return zone["name"]
    return "Other"


def fetch_hotspots(days: int = 1, country: str = "NGA") -> dict:
    """
    Fetch thermal hotspot data from NASA FIRMS API.
    Returns a GeoJSON FeatureCollection.

    Args:
        days: Number of past days to query (1–10).
        country: ISO 3166-1 alpha-3 country code.

    Raises:
        ValueError: If API key is missing.
        requests.HTTPError: If the FIRMS API returns an error.
    """
    if not FIRMS_API_KEY:
        # Return mock data if no API key is set (for development)
        return _mock_hotspots()

    url = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/VIIRS_SNPP_NRT/{country}/{days}/"

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    return _parse_csv_to_geojson(response.text)


def _parse_csv_to_geojson(csv_text: str) -> dict:
    """Parse NASA FIRMS CSV response into GeoJSON FeatureCollection."""
    features = []
    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        try:
            lat = float(row.get("latitude", 0))
            lon = float(row.get("longitude", 0))
            brightness = float(row.get("bright_ti4", 0))
            confidence = row.get("confidence", "n").strip().upper()
            acq_date = row.get("acq_date", "")
            acq_time = row.get("acq_time", "")
            frp = row.get("frp", "0")

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "properties": {
                    "brightness": brightness,
                    "confidence": confidence,
                    "acq_date": acq_date,
                    "acq_time": acq_time,
                    "frp": frp,
                    "red_zone": _get_red_zone(lat, lon),
                    "source": "VIIRS_SNPP_NRT"
                }
            }
            features.append(feature)
        except (ValueError, KeyError):
            continue

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "NASA FIRMS",
            "sensor": "VIIRS SNPP NRT"
        }
    }


def _mock_hotspots() -> dict:
    """
    Returns realistic mock hotspot data for development
    when no NASA FIRMS API key is configured.
    """
    mock_points = [
        (12.0, 8.5,  "H", "2026-04-14", "0130", "Northwest Corridor"),
        (11.5, 13.2, "H", "2026-04-14", "0145", "Northeast Corridor"),
        (13.1, 5.8,  "N", "2026-04-14", "0200", "Northwest Corridor"),
        (10.2, 12.8, "H", "2026-04-14", "0210", "Northeast Corridor"),
        (9.5,  6.3,  "L", "2026-04-14", "0220", "North Central"),
        (12.7, 7.1,  "N", "2026-04-14", "0235", "Northwest Corridor"),
        (11.9, 14.4, "H", "2026-04-14", "0250", "Northeast Corridor"),
        (8.3,  4.5,  "L", "2026-04-14", "0305", "Other"),
    ]

    features = []
    for lat, lon, conf, date, time, zone in mock_points:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "brightness": 320.0 if conf == "H" else 305.0,
                "confidence": conf,
                "acq_date": date,
                "acq_time": time,
                "frp": "25.4" if conf == "H" else "10.1",
                "red_zone": zone,
                "source": "MOCK_DATA"
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": "MOCK DATA — add NASA_FIRMS_API_KEY to .env for live data",
            "sensor": "VIIRS SNPP NRT"
        }
    }