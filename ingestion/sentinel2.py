"""
ingestion/sentinel2.py
──────────────────────
Sentinel-2 imagery acquisition via Copernicus Data Space Ecosystem (CDSE).
Handles authentication, scene search, and band download for vegetation analysis.
"""

import os
import json
import hashlib
import logging
import requests
import numpy as np
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("eagleeye.sentinel2")

# ── Constants ─────────────────────────────────────────────────
CDSE_AUTH_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1"
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Sentinel-2 band resolutions (metres)
BAND_RESOLUTIONS = {
    "B02": 10, "B03": 10, "B04": 10, "B08": 10,      # Visible + NIR
    "B05": 20, "B06": 20, "B07": 20, "B8A": 20,      # Red-edge + narrow NIR
    "B11": 20, "B12": 20,                               # SWIR
    "B01": 60, "B09": 60,                               # Atmospheric
    "SCL": 20,                                           # Scene classification
}

# Nigeria bounding box (loose)
NIGERIA_BBOX = {
    "west": 2.67,
    "south": 4.27,
    "east": 14.68,
    "north": 13.89,
}

# Known high-risk monitoring zones
MONITORING_ZONES = {
    "zamfara_corridor": {
        "name": "Zamfara Forest Corridor",
        "bbox": [6.0, 11.5, 7.5, 12.8],
        "risk_level": "critical",
        "description": "Northwest banditry corridor",
    },
    "sambisa_forest": {
        "name": "Sambisa Forest",
        "bbox": [13.0, 10.5, 14.2, 11.8],
        "risk_level": "critical",
        "description": "Northeast insurgency zone",
    },
    "niger_delta": {
        "name": "Niger Delta Creeks",
        "bbox": [5.5, 4.3, 7.5, 5.8],
        "risk_level": "high",
        "description": "Oil theft and militant camps",
    },
    "kaduna_southern": {
        "name": "Southern Kaduna",
        "bbox": [7.2, 9.0, 8.8, 10.2],
        "risk_level": "high",
        "description": "Communal conflict zone",
    },
    "benue_valley": {
        "name": "Benue Valley",
        "bbox": [7.5, 6.8, 10.0, 8.2],
        "risk_level": "moderate",
        "description": "Herder-farmer conflict belt",
    },
}


@dataclass
class SentinelScene:
    """Metadata for a single Sentinel-2 scene."""
    scene_id: str
    datetime: str
    cloud_cover: float
    bbox: List[float]
    tile_id: str
    product_type: str
    download_url: Optional[str] = None
    processing_level: str = "L2A"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BandData:
    """Container for a downloaded band array and its metadata."""
    band_name: str
    data: np.ndarray
    resolution: int
    scene_id: str
    crs: str = "EPSG:4326"
    transform: Optional[Tuple] = None


class CopernicusAuthError(Exception):
    """Raised when Copernicus authentication fails."""
    pass


class SceneSearchError(Exception):
    """Raised when scene catalogue search fails."""
    pass


class Sentinel2Client:
    """
    Client for the Copernicus Data Space Ecosystem.

    Handles:
      - OAuth2 authentication
      - OData catalogue search for Sentinel-2 L2A products
      - Sentinel Hub Processing API for band retrieval
      - Local tile caching
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cache_dir: str = "./data/sentinel2_cache",
    ):
        self.username = username or os.getenv("COPERNICUS_USER", "")
        self.password = password or os.getenv("COPERNICUS_PASSWORD", "")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

        if not self.username or not self.password:
            logger.warning(
                "Copernicus credentials not set. "
                "Set COPERNICUS_USER and COPERNICUS_PASSWORD in .env"
            )

    # ── Authentication ────────────────────────────────────────

    def _authenticate(self) -> str:
        """Obtain or refresh OAuth2 access token from CDSE."""
        if self._access_token and self._token_expiry and datetime.utcnow() < self._token_expiry:
            return self._access_token

        logger.info("Authenticating with Copernicus Data Space...")

        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": "cdse-public",
        }

        try:
            resp = requests.post(CDSE_AUTH_URL, data=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise CopernicusAuthError(f"Authentication failed: {e}")

        token_data = resp.json()
        self._access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 600)
        self._token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 60)

        logger.info("Copernicus authentication successful (expires in %ds)", expires_in)
        return self._access_token

    @property
    def _auth_headers(self) -> Dict[str, str]:
        token = self._authenticate()
        return {"Authorization": f"Bearer {token}"}

    # ── Catalogue Search ──────────────────────────────────────

    def search_scenes(
        self,
        bbox: List[float],
        start_date: str,
        end_date: str,
        max_cloud_cover: float = 30.0,
        max_results: int = 20,
        processing_level: str = "L2A",
    ) -> List[SentinelScene]:
        """
        Search the CDSE OData catalogue for Sentinel-2 scenes.

        Parameters
        ----------
        bbox : [west, south, east, north] in WGS84
        start_date : ISO date string (YYYY-MM-DD)
        end_date : ISO date string (YYYY-MM-DD)
        max_cloud_cover : Maximum cloud cover percentage (0–100)
        max_results : Maximum number of results to return
        processing_level : "L1C" or "L2A" (atmospherically corrected)
        """
        west, south, east, north = bbox

        # OData polygon filter (WKT-style via OData geo.intersects)
        footprint = (
            f"OData.CSC.Intersects(area=geography'SRID=4326;"
            f"POLYGON(({west} {south},{east} {south},"
            f"{east} {north},{west} {north},{west} {south}))')"
        )

        collection = f"SENTINEL-2" if processing_level == "L1C" else "SENTINEL-2"
        product_type = f"S2MSI{processing_level}"

        filter_parts = [
            f"Collection/Name eq '{collection}'",
            footprint,
            f"ContentDate/Start gt {start_date}T00:00:00.000Z",
            f"ContentDate/Start lt {end_date}T23:59:59.999Z",
            f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value lt {max_cloud_cover})",
            f"contains(Name,'{product_type}')",
        ]

        odata_filter = " and ".join(filter_parts)

        params = {
            "$filter": odata_filter,
            "$orderby": "ContentDate/Start desc",
            "$top": max_results,
            "$expand": "Attributes",
        }

        logger.info(
            "Searching Sentinel-2 scenes: bbox=%s, dates=%s to %s, cloud<%.0f%%",
            bbox, start_date, end_date, max_cloud_cover,
        )

        try:
            resp = requests.get(
                f"{CDSE_CATALOGUE_URL}/Products",
                params=params,
                headers=self._auth_headers,
                timeout=60,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SceneSearchError(f"Catalogue search failed: {e}")

        results = resp.json().get("value", [])
        scenes = []

        for item in results:
            cloud_cover = 0.0
            for attr in item.get("Attributes", []):
                if attr.get("Name") == "cloudCover":
                    cloud_cover = attr.get("Value", 0.0)
                    break

            # Extract tile ID from product name
            name = item.get("Name", "")
            parts = name.split("_")
            tile_id = ""
            for p in parts:
                if len(p) == 6 and p[0] == "T" and p[1:3].isdigit():
                    tile_id = p
                    break

            scene = SentinelScene(
                scene_id=item.get("Id", ""),
                datetime=item.get("ContentDate", {}).get("Start", ""),
                cloud_cover=cloud_cover,
                bbox=bbox,
                tile_id=tile_id,
                product_type=product_type,
                download_url=f"{CDSE_CATALOGUE_URL}/Products({item.get('Id')})/",
                processing_level=processing_level,
            )
            scenes.append(scene)

        logger.info("Found %d Sentinel-2 scenes", len(scenes))
        return scenes

    # ── Band Retrieval via Sentinel Hub Processing API ────────

    def get_bands(
        self,
        bbox: List[float],
        date: str,
        bands: List[str] = None,
        resolution: int = 10,
        width: int = 512,
        height: int = 512,
    ) -> Dict[str, np.ndarray]:
        """
        Retrieve specific band data using Sentinel Hub Processing API.

        Parameters
        ----------
        bbox : [west, south, east, north] in WGS84
        date : ISO date string (scene date)
        bands : List of band names e.g. ["B04", "B08", "B11", "SCL"]
        resolution : Spatial resolution in metres
        width, height : Output image dimensions in pixels
        """
        if bands is None:
            bands = ["B04", "B08"]  # Red + NIR for NDVI

        # Check cache first
        cache_key = self._cache_key(bbox, date, bands, resolution)
        cached = self._load_from_cache(cache_key)
        if cached is not None:
            logger.info("Loaded bands from cache: %s", cache_key)
            return cached

        west, south, east, north = bbox

        evalscript = self._build_evalscript(bands)

        request_body = {
            "input": {
                "bounds": {
                    "bbox": [west, south, east, north],
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {
                                "from": f"{date}T00:00:00Z",
                                "to": f"{date}T23:59:59Z",
                            },
                            "maxCloudCoverage": 40,
                        },
                    }
                ],
            },
            "output": {
                "width": width,
                "height": height,
                "responses": [
                    {
                        "identifier": "default",
                        "format": {"type": "image/tiff"},
                    }
                ],
            },
            "evalscript": evalscript,
        }

        logger.info(
            "Requesting bands %s for bbox=%s, date=%s",
            bands, bbox, date,
        )

        try:
            resp = requests.post(
                CDSE_PROCESS_URL,
                json=request_body,
                headers={
                    **self._auth_headers,
                    "Content-Type": "application/json",
                    "Accept": "image/tiff",
                },
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Band retrieval failed: %s", e)
            raise

        # Parse multi-band TIFF response
        band_arrays = self._parse_tiff_response(resp.content, bands)

        # Cache the result
        self._save_to_cache(cache_key, band_arrays)

        return band_arrays

    def _build_evalscript(self, bands: List[str]) -> str:
        """Build a Sentinel Hub evalscript that returns requested bands."""
        input_bands = ", ".join(f'"{b}"' for b in bands)
        output_bands = len(bands)

        # Return raw reflectance values scaled to 0–10000
        sample_lines = []
        for i, band in enumerate(bands):
            sample_lines.append(f"sample.{band}")

        return_values = ", ".join(sample_lines)

        evalscript = f"""//VERSION=3
function setup() {{
  return {{
    input: [{{
      bands: [{input_bands}],
      units: "DN"
    }}],
    output: {{
      bands: {output_bands},
      sampleType: "FLOAT32"
    }}
  }};
}}

function evaluatePixel(sample) {{
  return [{return_values}];
}}"""
        return evalscript

    def _parse_tiff_response(
        self, content: bytes, bands: List[str]
    ) -> Dict[str, np.ndarray]:
        """Parse a multi-band TIFF response into per-band numpy arrays."""
        try:
            import rasterio
            from rasterio.io import MemoryFile

            with MemoryFile(content) as memfile:
                with memfile.open() as dataset:
                    result = {}
                    for i, band_name in enumerate(bands):
                        result[band_name] = dataset.read(i + 1).astype(np.float32)
                    return result
        except ImportError:
            logger.warning(
                "rasterio not available — falling back to raw byte parsing. "
                "Install rasterio for proper GeoTIFF support."
            )
            # Minimal fallback: treat as raw float32 buffer
            arr = np.frombuffer(content, dtype=np.float32)
            chunk_size = len(arr) // len(bands) if len(bands) > 0 else len(arr)
            result = {}
            for i, band_name in enumerate(bands):
                start = i * chunk_size
                end = start + chunk_size
                side = int(np.sqrt(chunk_size))
                if side * side == chunk_size:
                    result[band_name] = arr[start:end].reshape(side, side)
                else:
                    result[band_name] = arr[start:end]
            return result

    # ── Caching ───────────────────────────────────────────────

    def _cache_key(
        self,
        bbox: List[float],
        date: str,
        bands: List[str],
        resolution: int,
    ) -> str:
        raw = f"{bbox}-{date}-{sorted(bands)}-{resolution}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _save_to_cache(self, key: str, data: Dict[str, np.ndarray]):
        cache_path = self.cache_dir / f"{key}.npz"
        np.savez_compressed(str(cache_path), **data)
        logger.debug("Cached band data: %s", cache_path)

    def _load_from_cache(self, key: str) -> Optional[Dict[str, np.ndarray]]:
        cache_path = self.cache_dir / f"{key}.npz"
        if cache_path.exists():
            loaded = np.load(str(cache_path))
            return dict(loaded)
        return None

    def clear_cache(self, older_than_days: int = 30):
        """Remove cached files older than the specified number of days."""
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        removed = 0
        for f in self.cache_dir.glob("*.npz"):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed += 1
        logger.info("Cleared %d cached files older than %d days", removed, older_than_days)
        return removed


# ── Convenience singleton ─────────────────────────────────────

_client: Optional[Sentinel2Client] = None


def get_sentinel2_client() -> Sentinel2Client:
    """Return a module-level Sentinel2Client singleton."""
    global _client
    if _client is None:
        _client = Sentinel2Client()
    return _client