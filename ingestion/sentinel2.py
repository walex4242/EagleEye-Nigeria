"""
ingestion/sentinel2.py
──────────────────────
Sentinel-2 imagery acquisition via Copernicus Data Space Ecosystem (CDSE).
Handles authentication, scene search, and band download for vegetation analysis.
Falls back to realistic synthetic data when credentials are not configured,
data is invalid, or dates are in the future.
"""

from __future__ import annotations

import os
import json
import hashlib
import logging
import tempfile
import requests
import numpy as np
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("eagleeye.sentinel2")

# ── Constants ─────────────────────────────────────────────────
CDSE_AUTH_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/"
    "CDSE/protocol/openid-connect/token"
)
CDSE_CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1"
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Sentinel-2 band resolutions (metres)
BAND_RESOLUTIONS: Dict[str, int] = {
    "B02": 10, "B03": 10, "B04": 10, "B08": 10,
    "B05": 20, "B06": 20, "B07": 20, "B8A": 20,
    "B11": 20, "B12": 20,
    "B01": 60, "B09": 60,
    "SCL": 20,
}

# Nigeria bounding box (loose)
NIGERIA_BBOX: Dict[str, float] = {
    "west": 2.67,
    "south": 4.27,
    "east": 14.68,
    "north": 13.89,
}

# Known high-risk monitoring zones
MONITORING_ZONES: Dict[str, Dict[str, Any]] = {
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BandData:
    """Container for a downloaded band array and its metadata."""

    band_name: str
    data: np.ndarray
    resolution: int
    scene_id: str
    crs: str = "EPSG:4326"
    transform: Optional[Tuple[float, ...]] = None


class CopernicusAuthError(Exception):
    """Raised when Copernicus authentication fails."""


class SceneSearchError(Exception):
    """Raised when scene catalogue search fails."""


class Sentinel2Client:
    """
    Client for the Copernicus Data Space Ecosystem.

    Handles:
      - OAuth2 authentication
      - OData catalogue search for Sentinel-2 L2A products
      - Sentinel Hub Processing API for band retrieval
      - Data validation (rejects empty / all-zero responses)
      - Future-date detection (no satellite data can exist)
      - Local tile caching
      - Realistic synthetic fallback for demo/development
    """

    # Minimum fraction of non-zero finite pixels to accept a band
    MIN_VALID_COVERAGE = 0.01  # 1%

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cache_dir: str = "./data/sentinel2_cache",
    ) -> None:
        self.username = username or os.getenv("COPERNICUS_USER", "")
        self.password = password or os.getenv("COPERNICUS_PASSWORD", "")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.configured = bool(self.username and self.password)

        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None

        if self.configured:
            print("[S2] Copernicus credentials found — real API mode")
        else:
            print("[S2] No Copernicus credentials — synthetic fallback active")
            logger.warning(
                "Copernicus credentials not set — synthetic fallback active. "
                "Set COPERNICUS_USER and COPERNICUS_PASSWORD in .env for real imagery."
            )

    # ── Authentication ────────────────────────────────────────

    def _authenticate(self) -> str:
        """Obtain or refresh OAuth2 access token from CDSE."""
        if (
            self._access_token is not None
            and self._token_expiry is not None
            and datetime.utcnow() < self._token_expiry
        ):
            return self._access_token

        logger.info("Authenticating with Copernicus Data Space...")

        payload: Dict[str, str] = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": "cdse-public",
        }

        try:
            resp = requests.post(CDSE_AUTH_URL, data=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise CopernicusAuthError(f"Authentication failed: {e}") from e

        token_data: Dict[str, Any] = resp.json()
        self._access_token = str(token_data["access_token"])
        expires_in = int(token_data.get("expires_in", 600))
        self._token_expiry = datetime.utcnow() + timedelta(
            seconds=expires_in - 60
        )

        logger.info(
            "Copernicus authentication successful (expires in %ds)",
            expires_in,
        )
        return self._access_token

    @property
    def _auth_headers(self) -> Dict[str, str]:
        token = self._authenticate()
        return {"Authorization": f"Bearer {token}"}

    # ── Date Helpers ──────────────────────────────────────────

    @staticmethod
    def _is_future_date(date_str: str) -> bool:
        """
        Check whether the requested date is in the future.
        Sentinel-2 cannot have imagery for dates that have not occurred yet.
        """
        try:
            requested = datetime.strptime(date_str, "%Y-%m-%d")
            return requested.date() > datetime.utcnow().date()
        except ValueError:
            return False

    @staticmethod
    def _clamp_date_to_present(date_str: str) -> str:
        """
        If a date is in the future, return today's date instead.
        Useful for seeding synthetic data with a sensible DOY.
        """
        try:
            requested = datetime.strptime(date_str, "%Y-%m-%d")
            if requested.date() > datetime.utcnow().date():
                return datetime.utcnow().strftime("%Y-%m-%d")
        except ValueError:
            pass
        return date_str

    # ── Data Validation ───────────────────────────────────────

    def _validate_band_data(self, data: Dict[str, np.ndarray]) -> bool:
        """
        Verify that fetched band data contains meaningful pixel values.

        Returns False if:
          - dict is empty
          - any band is entirely NaN / Inf
          - any band is entirely zero
          - any band has < MIN_VALID_COVERAGE non-zero finite pixels
        """
        if not data:
            print("[S2-VALIDATE] ✗ Empty band dictionary")
            return False

        for band_name, arr in data.items():
            if arr is None or arr.size == 0:
                print(f"[S2-VALIDATE] ✗ {band_name}: array is None or empty")
                return False

            if band_name == "SCL":
                # For SCL, class 0 = "no data" — need at least some real classes
                non_nodata = int(np.sum(arr != 0))
                if non_nodata == 0:
                    print(f"[S2-VALIDATE] ✗ {band_name}: all no-data (class 0)")
                    return False
                # Also check valid land classes (4=veg, 5=soil, 6=water)
                valid_land = int(np.sum(np.isin(arr, [4, 5, 6])))
                coverage = valid_land / max(arr.size, 1)
                if coverage < self.MIN_VALID_COVERAGE:
                    print(
                        f"[S2-VALIDATE] ✗ {band_name}: only {coverage:.2%} "
                        f"valid land pixels (need ≥{self.MIN_VALID_COVERAGE:.0%})"
                    )
                    return False
                continue

            # Normal reflectance bands
            finite_mask = np.isfinite(arr)
            finite_count = int(np.sum(finite_mask))

            if finite_count == 0:
                print(f"[S2-VALIDATE] ✗ {band_name}: no finite values at all")
                return False

            nonzero_count = int(np.sum(arr[finite_mask] != 0))
            coverage = nonzero_count / max(arr.size, 1)

            if nonzero_count == 0:
                print(f"[S2-VALIDATE] ✗ {band_name}: all zeros (empty tile)")
                return False

            if coverage < self.MIN_VALID_COVERAGE:
                print(
                    f"[S2-VALIDATE] ✗ {band_name}: only {coverage:.2%} "
                    f"non-zero coverage (need ≥{self.MIN_VALID_COVERAGE:.0%})"
                )
                return False

            print(
                f"[S2-VALIDATE]   {band_name}: OK — "
                f"{coverage:.1%} coverage, "
                f"range=[{np.nanmin(arr):.1f}, {np.nanmax(arr):.1f}]"
            )

        print(f"[S2-VALIDATE] ✓ All {len(data)} bands passed validation")
        return True

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
        """Search the CDSE OData catalogue for Sentinel-2 scenes."""
        west, south, east, north = bbox

        footprint = (
            f"OData.CSC.Intersects(area=geography'SRID=4326;"
            f"POLYGON(({west} {south},{east} {south},"
            f"{east} {north},{west} {north},{west} {south}))')"
        )

        collection = "SENTINEL-2"
        product_type = f"S2MSI{processing_level}"

        filter_parts = [
            f"Collection/Name eq '{collection}'",
            footprint,
            f"ContentDate/Start gt {start_date}T00:00:00.000Z",
            f"ContentDate/Start lt {end_date}T23:59:59.999Z",
            (
                "Attributes/OData.CSC.DoubleAttribute/any("
                "att:att/Name eq 'cloudCover' and "
                "att/OData.CSC.DoubleAttribute/Value lt "
                f"{max_cloud_cover})"
            ),
            f"contains(Name,'{product_type}')",
        ]

        odata_filter = " and ".join(filter_parts)

        params: Dict[str, Any] = {
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
            raise SceneSearchError(f"Catalogue search failed: {e}") from e

        results: List[Dict[str, Any]] = resp.json().get("value", [])
        scenes: List[SentinelScene] = []

        for item in results:
            cloud_cover = 0.0
            for attr in item.get("Attributes", []):
                if attr.get("Name") == "cloudCover":
                    cloud_cover = float(attr.get("Value", 0.0))
                    break

            name: str = item.get("Name", "")
            parts = name.split("_")
            tile_id = ""
            for p in parts:
                if len(p) == 6 and p[0] == "T" and p[1:3].isdigit():
                    tile_id = p
                    break

            scene_id: str = item.get("Id", "")
            content_date: Dict[str, str] = item.get("ContentDate", {})

            scene = SentinelScene(
                scene_id=scene_id,
                datetime=content_date.get("Start", ""),
                cloud_cover=cloud_cover,
                bbox=bbox,
                tile_id=tile_id,
                product_type=product_type,
                download_url=(
                    f"{CDSE_CATALOGUE_URL}/Products({scene_id})/"
                ),
                processing_level=processing_level,
            )
            scenes.append(scene)

        logger.info("Found %d Sentinel-2 scenes", len(scenes))
        return scenes

    # ── Band Retrieval ────────────────────────────────────────

    def get_bands(
        self,
        bbox: List[float],
        date: str,
        bands: Optional[List[str]] = None,
        resolution: int = 10,
        width: int = 512,
        height: int = 512,
         force_synthetic: bool = False,
    ) -> Dict[str, np.ndarray]:
        """
        Retrieve specific band data for a given bounding box and date.

        Pipeline:
          1. Reject future dates immediately (no satellite data can exist).
          2. Check local cache for a valid previous download.
          3. Try real Copernicus API (if credentials are configured).
          4. Validate the response (reject all-zero / empty tiles).
          5. Fall back to realistic synthetic data if anything above fails.

        Returns a dict mapping band name → 2-D numpy array.
        """
        if bands is None:
            bands = ["B04", "B08"]

        print(
            f"[S2] get_bands called: date={date}, bands={bands}, "
            f"configured={self.configured}"
        )
        print(f"[S2] System UTC time: {datetime.utcnow().isoformat()}")
        
        # ── Force synthetic if explicitly requested ──           # ← ADD THIS BLOCK
        if force_synthetic:
         print(f"[S2] Force-synthetic requested for date={date}")
        effective_date = self._clamp_date_to_present(date) if self._is_future_date(date) else date
        result = self._generate_synthetic_bands(bbox, effective_date, bands, width, height)
        self._log_band_stats(result, source="SYNTH-FORCED")
        return result

        # ── Guard: future dates can never have real imagery ──
        if self._is_future_date(date):
            print(
                f"[S2] ⚠ Date {date} is in the future — "
                f"no satellite imagery exists. Using synthetic fallback."
            )
            effective_date = self._clamp_date_to_present(date)
            result = self._generate_synthetic_bands(
                bbox, effective_date, bands, width, height
            )
            self._log_band_stats(result, source="SYNTH-FUTURE")
            # Cache under the original date so repeat calls are fast
            cache_key = self._cache_key(bbox, date, bands, resolution)
            self._save_to_cache(cache_key, result)
            return result

        # ── Check cache ──
        cache_key = self._cache_key(bbox, date, bands, resolution)
        cached = self._load_from_cache(cache_key)
        if cached is not None:
            if self._validate_band_data(cached):
                print(f"[S2] ✓ Cache hit (valid): {cache_key}")
                return cached
            else:
                print(f"[S2] ✗ Cache hit but INVALID data — deleting & regenerating")
                bad_path = self.cache_dir / f"{cache_key}.npz"
                bad_path.unlink(missing_ok=True)

        # ── Try real Copernicus API ──
        if self.configured:
            try:
                print(f"[S2] Attempting real Copernicus API fetch...")
                result = self._fetch_real_bands(
                    bbox, date, bands, resolution, width, height,
                )

                if self._validate_band_data(result):
                    self._save_to_cache(cache_key, result)
                    print(f"[S2] ✓ Real API fetch successful with valid data")
                    return result
                else:
                    print(
                        f"[S2] ✗ Real API returned HTTP 200 but data is "
                        f"empty/invalid (likely no coverage for this date/bbox). "
                        f"Falling back to synthetic."
                    )
            except CopernicusAuthError as e:
                print(f"[S2] ✗ Authentication failed: {e} — falling back to synthetic")
                logger.warning("Copernicus auth failed: %s", e)
            except Exception as e:
                print(f"[S2] ✗ Real API failed: {e} — falling back to synthetic")
                logger.warning(
                    "Real Sentinel-2 fetch failed (%s), falling back to synthetic",
                    e,
                )

        # ── Synthetic fallback ──
        print(f"[S2-SYNTH] Generating synthetic data for date={date}...")
        result = self._generate_synthetic_bands(bbox, date, bands, width, height)

        if not self._validate_band_data(result):
            # This should never happen but guard against bad RNG edge cases
            print("[S2-SYNTH] ⚠ Synthetic generation produced invalid data — retrying with offset seed")
            offset_date = f"{date}-retry"
            result = self._generate_synthetic_bands(bbox, offset_date, bands, width, height)

        self._log_band_stats(result, source="SYNTH")
        self._save_to_cache(cache_key, result)
        print(f"[S2-SYNTH] ✓ Synthetic data generated and cached: {cache_key}")
        return result

    def _log_band_stats(
        self, result: Dict[str, np.ndarray], source: str = "SYNTH",
    ) -> None:
        """Print diagnostic stats for each band array."""
        for band_name, arr in result.items():
            finite_count = int(np.sum(np.isfinite(arr)))
            nonzero_count = int(np.sum(arr != 0))
            print(
                f"[S2-{source}]   {band_name}: shape={arr.shape}, "
                f"finite={finite_count}/{arr.size}, "
                f"nonzero={nonzero_count}, "
                f"min={np.nanmin(arr):.1f}, max={np.nanmax(arr):.1f}"
            )

    def _fetch_real_bands(
        self,
        bbox: List[float],
        date: str,
        bands: List[str],
        resolution: int,
        width: int,
        height: int,
    ) -> Dict[str, np.ndarray]:
        """Fetch real band data via Sentinel Hub Processing API."""
        west, south, east, north = bbox
        evalscript = self._build_evalscript(bands)

        request_body: Dict[str, Any] = {
            "input": {
                "bounds": {
                    "bbox": [west, south, east, north],
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326",
                    },
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
            "Requesting bands %s for bbox=%s, date=%s", bands, bbox, date,
        )

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

        # Check content type
        content_type = resp.headers.get("Content-Type", "")
        if "tiff" not in content_type and "octet" not in content_type:
            logger.warning(
                "Unexpected Content-Type from Processing API: %s",
                content_type,
            )
            # Might be an error JSON response disguised as 200
            try:
                error_body = resp.json()
                raise RuntimeError(
                    f"Processing API returned non-TIFF response: {error_body}"
                )
            except (ValueError, KeyError):
                pass

        if len(resp.content) < 100:
            raise RuntimeError(
                f"Processing API response too small ({len(resp.content)} bytes) "
                f"— likely empty or error."
            )

        return self._parse_tiff_response(resp.content, bands)

    # ── Synthetic Data Generation ─────────────────────────────

    def _generate_synthetic_bands(
        self,
        bbox: List[float],
        date: str,
        bands: List[str],
        width: int = 512,
        height: int = 512,
    ) -> Dict[str, np.ndarray]:
        """
        Generate realistic synthetic Sentinel-2 band data.

        Simulates:
        - Realistic per-band reflectance values
        - Spatially coherent vegetation patterns
        - Latitude-dependent vegetation density (Sahel→Forest)
        - Seasonal variation (dry vs wet season)
        - Clearing patches in known conflict zones
        - Burn scars near clearings
        - ~10-15% realistic cloud cover
        """
        west, south, east, north = bbox

        # Deterministic RNG seeded from bbox + date
        seed_str = f"{bbox}-{date}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        rng = np.random.RandomState(seed)

        # ── Seasonal factor ──
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            day_of_year = dt.timetuple().tm_yday
        except ValueError:
            day_of_year = 100

        # Nigeria wet season ~ May-Oct (DOY 120-300)
        seasonal_factor = 0.3 * np.sin(
            2 * np.pi * (day_of_year - 120) / 365
        ) + 0.5

        # ── Regional vegetation density ──
        center_lat = (north + south) / 2
        center_lon = (east + west) / 2

        # Northern Sahel = sparse, Southern Forest = dense
        veg_density = np.clip(1.0 - (center_lat - 4.0) / 12.0, 0.2, 0.9)
        veg_density *= seasonal_factor

        # ── Spatially coherent vegetation pattern ──
        veg_base = np.zeros((height, width), dtype=np.float64)
        for scale in [4, 8, 16, 32]:
            noise_h = max(height // scale, 1)
            noise_w = max(width // scale, 1)
            noise = rng.randn(noise_h, noise_w)
            noise_up = np.kron(noise, np.ones((scale, scale)))[:height, :width]
            veg_base += noise_up / scale

        veg_range = veg_base.max() - veg_base.min()
        if veg_range > 0:
            veg_base = (veg_base - veg_base.min()) / veg_range
        veg_pattern = veg_base * veg_density

        # ── Conflict zone clearing patches ──
        is_conflict_zone = (
            (11.0 <= center_lat <= 14.0 and 5.5 <= center_lon <= 8.0)
            or (10.0 <= center_lat <= 13.0 and 12.0 <= center_lon <= 15.0)
        )

        clearing_mask = np.zeros((height, width), dtype=bool)
        burn_mask = np.zeros((height, width), dtype=bool)
        num_clearings = 0

        if is_conflict_zone:
            num_clearings = rng.randint(2, 6)
            for _ in range(num_clearings):
                cy = rng.randint(10, max(height - 10, 11))
                cx = rng.randint(10, max(width - 10, 11))
                radius = rng.randint(3, 12)
                yy, xx = np.ogrid[-cy:height - cy, -cx:width - cx]
                patch = (yy * yy + xx * xx) <= (radius * radius)
                clearing_mask |= patch

                # Some clearings also have burn evidence
                if rng.random() > 0.5:
                    burn_mask |= (patch & (rng.random((height, width)) > 0.4))

        # ── Generate each band ──
        result: Dict[str, np.ndarray] = {}

        for band in bands:
            if band == "SCL":
                result[band] = self._generate_scl(height, width, rng)

            elif band == "B02":
                # Blue (490nm) — low veg reflectance
                blue = 300.0 + rng.randn(height, width) * 50.0
                blue += veg_pattern * 200.0
                result[band] = np.clip(blue, 100, 2000).astype(np.float32)

            elif band == "B03":
                # Green (560nm) — moderate veg reflectance
                green = 350.0 + rng.randn(height, width) * 60.0
                green += veg_pattern * 400.0
                result[band] = np.clip(green, 100, 2500).astype(np.float32)

            elif band == "B04":
                # Red (665nm) — absorbed by vegetation
                red = 400.0 + rng.randn(height, width) * 80.0
                red -= veg_pattern * 600.0
                red[clearing_mask] += 400.0
                result[band] = np.clip(red, 100, 3000).astype(np.float32)

            elif band == "B08":
                # NIR (842nm) — strongly reflected by vegetation
                nir = 800.0 + rng.randn(height, width) * 100.0
                nir += veg_pattern * 2500.0
                nir[clearing_mask] -= 1500.0
                result[band] = np.clip(nir, 200, 5000).astype(np.float32)

            elif band == "B8A":
                # Narrow NIR (865nm) — similar to B08 but narrower
                nir_narrow = 750.0 + rng.randn(height, width) * 90.0
                nir_narrow += veg_pattern * 2300.0
                nir_narrow[clearing_mask] -= 1400.0
                result[band] = np.clip(nir_narrow, 200, 4800).astype(np.float32)

            elif band == "B05":
                # Red Edge 1 (705nm)
                re1 = 450.0 + rng.randn(height, width) * 70.0
                re1 += veg_pattern * 800.0
                result[band] = np.clip(re1, 100, 3000).astype(np.float32)

            elif band == "B06":
                # Red Edge 2 (740nm)
                re2 = 500.0 + rng.randn(height, width) * 80.0
                re2 += veg_pattern * 1200.0
                result[band] = np.clip(re2, 100, 3500).astype(np.float32)

            elif band == "B07":
                # Red Edge 3 (783nm)
                re3 = 550.0 + rng.randn(height, width) * 85.0
                re3 += veg_pattern * 1800.0
                result[band] = np.clip(re3, 100, 4000).astype(np.float32)

            elif band == "B11":
                # SWIR1 (1610nm) — moisture sensitive
                swir1 = 600.0 + rng.randn(height, width) * 100.0
                swir1 -= veg_pattern * 400.0
                result[band] = np.clip(swir1, 100, 3000).astype(np.float32)

            elif band == "B12":
                # SWIR2 (2190nm) — burn scar detection
                swir2 = 400.0 + rng.randn(height, width) * 80.0
                swir2 -= veg_pattern * 300.0
                swir2[burn_mask] += 800.0
                result[band] = np.clip(swir2, 100, 3000).astype(np.float32)

            elif band == "B01":
                # Coastal aerosol (443nm)
                coastal = 250.0 + rng.randn(height, width) * 40.0
                coastal += veg_pattern * 150.0
                result[band] = np.clip(coastal, 50, 1800).astype(np.float32)

            elif band == "B09":
                # Water vapour (945nm)
                wv = 100.0 + rng.randn(height, width) * 30.0
                result[band] = np.clip(wv, 10, 800).astype(np.float32)

            else:
                # Generic fallback band
                generic = 500.0 + rng.randn(height, width) * 100.0
                result[band] = np.clip(generic, 100, 3000).astype(np.float32)

        print(
            f"[S2-SYNTH] Generated: {width}x{height}, {len(bands)} bands, "
            f"veg={veg_density:.2f}, seasonal={seasonal_factor:.2f}, "
            f"conflict={is_conflict_zone}, clearings={num_clearings}"
        )

        return result

    @staticmethod
    def _generate_scl(
        height: int, width: int, rng: np.random.RandomState,
    ) -> np.ndarray:
        """
        Generate realistic Scene Classification Layer.

        Classes: 0=No data, 1=Saturated, 2=Dark, 3=Cloud shadow,
        4=Vegetation, 5=Bare soil, 6=Water, 7=Unclassified,
        8=Cloud med, 9=Cloud high, 10=Cirrus, 11=Snow
        """
        # Start mostly vegetation (class 4 = VALID)
        scl = np.full((height, width), 4, dtype=np.uint8)

        # ~30% bare soil (class 5 = VALID)
        soil_mask = rng.random((height, width)) > 0.7
        scl[soil_mask] = 5

        # ~2% water bodies (class 6 = VALID)
        water_mask = rng.random((height, width)) > 0.98
        scl[water_mask] = 6

        # ~10-15% cloud patches (class 8,9 = INVALID) — spatially coherent
        cloud_pct = rng.uniform(0.08, 0.15)
        cloud_h = max(height // 8, 1)
        cloud_w = max(width // 8, 1)
        cloud_seeds = rng.random((cloud_h, cloud_w))
        cloud_up = np.kron(
            cloud_seeds, np.ones((8, 8))
        )[:height, :width]
        cloud_mask = cloud_up < cloud_pct
        num_cloud = int(np.sum(cloud_mask))
        if num_cloud > 0:
            cloud_values = rng.choice([8, 9], size=num_cloud)
            scl[cloud_mask] = cloud_values

        # ~3% thin cirrus (class 10 = INVALID)
        cirrus_mask = (rng.random((height, width)) < 0.03) & ~cloud_mask
        scl[cirrus_mask] = 10

        # ~5% cloud shadow (class 3 = INVALID) — offset from clouds
        shadow_mask = np.roll(cloud_mask, shift=5, axis=0) & ~cloud_mask
        scl[shadow_mask] = 3

        # Debug output
        invalid_classes = {0, 1, 3, 8, 9, 10}
        invalid_count = int(np.sum(np.isin(scl, list(invalid_classes))))
        valid_count = scl.size - invalid_count
        print(
            f"[S2-SYNTH]   SCL: {valid_count}/{scl.size} valid pixels "
            f"({100.0 * valid_count / max(scl.size, 1):.1f}%), "
            f"clouds={num_cloud}, cirrus={int(np.sum(cirrus_mask))}, "
            f"shadow={int(np.sum(shadow_mask))}"
        )

        return scl

    # ── Evalscript Builder ────────────────────────────────────

    def _build_evalscript(self, bands: List[str]) -> str:
        """Build a Sentinel Hub evalscript that returns requested bands."""
        input_bands = ", ".join(f'"{b}"' for b in bands)
        output_bands = len(bands)

        sample_lines: List[str] = []
        for band in bands:
            sample_lines.append(f"sample.{band}")
        return_values = ", ".join(sample_lines)

        return f"""//VERSION=3
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

    # ── TIFF Parsing ──────────────────────────────────────────

    def _parse_tiff_response(
        self, content: bytes, bands: List[str],
    ) -> Dict[str, np.ndarray]:
        """Parse a multi-band TIFF response into per-band numpy arrays."""
        try:
            import rasterio
            from rasterio.io import MemoryFile

            with MemoryFile(content) as memfile:
                with memfile.open() as dataset:
                    result: Dict[str, np.ndarray] = {}
                    for i, band_name in enumerate(bands):
                        band_arr = dataset.read(i + 1).astype(np.float32)
                        result[band_name] = band_arr
                        logger.debug(
                            "Parsed %s: shape=%s, range=[%.1f, %.1f]",
                            band_name, band_arr.shape,
                            np.nanmin(band_arr), np.nanmax(band_arr),
                        )
                    return result
        except ImportError:
            logger.warning(
                "rasterio not available — falling back to raw byte parsing."
            )
            arr = np.frombuffer(content, dtype=np.float32)
            num_bands = max(len(bands), 1)
            chunk_size = len(arr) // num_bands
            result_fallback: Dict[str, np.ndarray] = {}
            for i, band_name in enumerate(bands):
                start = i * chunk_size
                end = start + chunk_size
                side = int(np.sqrt(float(chunk_size)))
                if side * side == chunk_size:
                    result_fallback[band_name] = arr[start:end].reshape(side, side)
                else:
                    result_fallback[band_name] = arr[start:end]
            return result_fallback

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

    def _save_to_cache(
        self, key: str, data: Dict[str, np.ndarray],
    ) -> None:
        cache_path = self.cache_dir / f"{key}.npz"
        with tempfile.NamedTemporaryFile(
            dir=str(self.cache_dir),
            suffix=".npz",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name

        try:
            arrays_to_save: Dict[str, Any] = {
                band_name: band_array
                for band_name, band_array in data.items()
            }
            np.savez_compressed(tmp_path, **arrays_to_save)
            Path(tmp_path).replace(cache_path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        logger.debug("Cached band data: %s", cache_path)

    def _load_from_cache(
        self, key: str,
    ) -> Optional[Dict[str, np.ndarray]]:
        cache_path = self.cache_dir / f"{key}.npz"
        if cache_path.exists():
            try:
                loaded = np.load(str(cache_path))
                return dict(loaded)
            except Exception as e:
                print(f"[S2] ✗ Cache load failed: {e} — deleting corrupt cache")
                cache_path.unlink(missing_ok=True)
                return None
        return None

    def get_cached_files(self) -> int:
        """Return count of cached files."""
        return len(list(self.cache_dir.glob("*.npz")))

    def clear_cache(self, older_than_days: int = 30) -> int:
        """Remove cached .npz files older than the specified number of days."""
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        removed = 0
        for cache_file in self.cache_dir.glob("*.npz"):
            file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if file_mtime < cutoff:
                cache_file.unlink()
                removed += 1
        logger.info(
            "Cleared %d cached files older than %d days",
            removed, older_than_days,
        )
        return removed

    def clear_all_cache(self) -> int:
        """Remove ALL cached .npz files. Useful after fixing data issues."""
        removed = 0
        for cache_file in self.cache_dir.glob("*.npz"):
            cache_file.unlink()
            removed += 1
        logger.info("Cleared all %d cached files", removed)
        print(f"[S2] Cleared all {removed} cached files")
        return removed


# ── Convenience singleton ─────────────────────────────────────

_client: Optional[Sentinel2Client] = None


def get_sentinel2_client() -> Sentinel2Client:
    global _client
    if _client is None:
        _client = Sentinel2Client()
    return _client