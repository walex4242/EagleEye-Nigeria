"""
ml.py
──────
API routes for ML-based satellite image analysis.

Integrates CampDetector with:
  - Manual image upload prediction
  - Coordinate-based analysis (download tile → predict)
  - Automated hotspot scanning (FIRMS → satellite → ML)
  - Area scanning (grid of tiles over a region)
  - Actionable threat recommendations

Endpoints:
  POST /ml/predict           — Upload image for classification
  POST /ml/predict-batch     — Upload multiple images
  POST /ml/analyze-location  — Analyze a lat/lon coordinate
  POST /ml/scan-hotspots     — Auto-scan recent FIRMS hotspots
  POST /ml/scan-area         — Scan a rectangular region
  GET  /ml/status            — Model health check
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
import traceback
import io
import os
import time
from typing import Any

router = APIRouter()


# ═══════════════════════════════════════════════════════
# SINGLETON DETECTOR (load model once, reuse)
# ═══════════════════════════════════════════════════════

_detector_instance: Any = None
_detector_load_attempted: bool = False


def _get_detector() -> Any:
    """
    Lazy-load CampDetector as a singleton.
    Avoids reloading the model on every request.
    Returns the detector instance or None if unavailable.
    """
    global _detector_instance, _detector_load_attempted

    if _detector_instance is not None:
        return _detector_instance

    if _detector_load_attempted:
        return None

    _detector_load_attempted = True

    try:
        from ml.detector import CampDetector, TORCH_AVAILABLE

        if not TORCH_AVAILABLE:
            print("[ML] PyTorch not available — detector disabled.")
            return None

        _detector_instance = CampDetector()

        if _detector_instance.model is not None:
            print("[ML] ✓ CampDetector loaded successfully.")
        else:
            print("[ML] ⚠️ CampDetector model is None.")
            _detector_instance = None

    except Exception as e:
        print(f"[ML] ❌ Failed to load CampDetector: {e}")
        _detector_instance = None

    return _detector_instance


# ═══════════════════════════════════════════════════════
# SATELLITE TILE FETCHER
# Downloads imagery around a coordinate for analysis
# ═══════════════════════════════════════════════════════

def _fetch_satellite_tile(
    lat: float,
    lon: float,
    zoom: int = 17,
    size: int = 224,
) -> Any:
    """
    Fetch a satellite image tile from Esri World Imagery
    for a given coordinate.

    Downloads a 3x3 grid of 256px tiles, stitches them,
    and crops the center to the requested size.

    Args:
        lat:  Latitude of the target location.
        lon:  Longitude of the target location.
        zoom: Tile zoom level (15-18). Higher = more detail.
        size: Output image size in pixels.

    Returns:
        PIL.Image.Image or None if download fails.
    """
    try:
        import math
        import requests
        from PIL import Image
        from io import BytesIO

        # Convert lat/lon to tile coordinates
        n = 2 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        y = int(
            (
                1.0
                - math.log(
                    math.tan(math.radians(lat))
                    + 1.0 / math.cos(math.radians(lat))
                )
                / math.pi
            )
            / 2.0
            * n
        )

        # Download 3x3 grid of tiles
        tile_size = 256
        tiles: list[list[Image.Image]] = []

        for dy in range(-1, 2):
            row: list[Image.Image] = []
            for dx in range(-1, 2):
                url = (
                    f"https://server.arcgisonline.com/ArcGIS/rest/services/"
                    f"World_Imagery/MapServer/tile/"
                    f"{zoom}/{y + dy}/{x + dx}"
                )
                resp = requests.get(
                    url,
                    timeout=10,
                    headers={
                        "User-Agent": "EagleEye-Nigeria/2.0 (satellite-research)",
                        "Referer": "https://www.arcgis.com/",
                    },
                )
                if resp.status_code == 200 and len(resp.content) > 1000:
                    tile = Image.open(BytesIO(resp.content)).convert("RGB")
                    row.append(tile)
                else:
                    return None
            tiles.append(row)

        # Stitch tiles into single image
        stitched = Image.new("RGB", (tile_size * 3, tile_size * 3))
        for row_idx, row in enumerate(tiles):
            for col_idx, tile in enumerate(row):
                stitched.paste(
                    tile.resize((tile_size, tile_size)),
                    (col_idx * tile_size, row_idx * tile_size),
                )

        # Crop center to desired size
        cx = (tile_size * 3) // 2
        cy = (tile_size * 3) // 2
        half = size // 2

        left = max(0, cx - half)
        top = max(0, cy - half)
        right = min(tile_size * 3, cx + half)
        bottom = min(tile_size * 3, cy + half)

        crop = stitched.crop((left, top, right, bottom))

        if crop.size != (size, size):
            crop = crop.resize((size, size))

        return crop

    except Exception as e:
        print(f"[ML] Tile fetch failed for ({lat}, {lon}): {e}")
        return None


def _is_valid_satellite_image(image: Any) -> bool:
    """
    Check if downloaded tile looks like valid satellite imagery.
    Rejects blank tiles, mostly-black ocean tiles, and all-white cloud tiles.
    """
    try:
        import numpy as np

        arr = np.array(image)
        std = float(np.std(arr))
        mean = float(np.mean(arr))

        if std < 10:
            return False  # Blank / uniform tile
        if mean < 20:
            return False  # Too dark (ocean/night)
        if mean > 240:
            return False  # Too bright (clouds)

        return True

    except Exception:
        return False


# ═══════════════════════════════════════════════════════
# RECOMMENDATION ENGINE
# ═══════════════════════════════════════════════════════

def _get_recommendation(result: dict[str, Any]) -> dict[str, Any]:
    """
    Generate actionable intelligence recommendations
    based on ML prediction results.

    Recommendation levels:
      CRITICAL — Immediate ground/aerial verification needed
      HIGH     — Priority surveillance scheduling
      MEDIUM   — Add to monitoring watchlist
      LOW      — Cleared or inconclusive
    """
    label = result.get("label", "")
    confidence = result.get("confidence", 0.0)
    flag = result.get("flag", False)

    if flag and confidence >= 0.9:
        return {
            "level": "CRITICAL",
            "action": "IMMEDIATE_INVESTIGATION",
            "message": (
                "High-confidence suspicious encampment detected. "
                "Recommend immediate drone/ground verification."
            ),
            "priority": 1,
        }
    elif flag and confidence >= 0.75:
        return {
            "level": "HIGH",
            "action": "PRIORITY_REVIEW",
            "message": (
                "Probable suspicious encampment. "
                "Schedule priority aerial surveillance."
            ),
            "priority": 2,
        }
    elif flag:
        return {
            "level": "MEDIUM",
            "action": "MONITOR",
            "message": (
                "Possible suspicious activity detected. "
                "Add to monitoring watchlist for repeat scanning."
            ),
            "priority": 3,
        }
    elif label == "legal_activity" and confidence >= 0.85:
        return {
            "level": "LOW",
            "action": "CLEAR",
            "message": (
                "Location classified as legal activity "
                "with high confidence."
            ),
            "priority": 5,
        }
    else:
        return {
            "level": "LOW",
            "action": "RECHECK",
            "message": (
                "Inconclusive result. Consider rescanning "
                "at different time or zoom level."
            ),
            "priority": 4,
        }


# ═══════════════════════════════════════════════════════
# HOTSPOT DATA FETCHER (for scan-hotspots)
# ═══════════════════════════════════════════════════════

async def _get_hotspots_for_scan(
    days: int,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Fetch recent hotspot data from FIRMS API for ML scanning.
    Filters to Nigeria bounding box (lat 4-14, lon 2.5-15).

    Args:
        days:  Number of days of data to fetch.
        limit: Maximum number of hotspots to return.

    Returns:
        List of hotspot dicts with lat, lon, brightness, etc.
    """
    try:
        import httpx
        import csv

        firms_key = os.getenv("FIRMS_MAP_KEY", "DEMO_KEY")
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
            f"{firms_key}/VIIRS_SNPP_NRT/world/{days}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            print(
                f"[ML] FIRMS API returned {resp.status_code} — "
                f"cannot fetch hotspots for scan."
            )
            return []

        lines = resp.text.strip().split("\n")
        if len(lines) < 2:
            return []

        reader = csv.DictReader(lines)
        hotspots: list[dict[str, Any]] = []

        for row in reader:
            try:
                lat = float(row.get("latitude", 0))
                lon = float(row.get("longitude", 0))

                # Filter to Nigeria bounding box
                if not (4.0 <= lat <= 14.0 and 2.5 <= lon <= 15.0):
                    continue

                hotspots.append({
                    "latitude": lat,
                    "longitude": lon,
                    "brightness": float(row.get("bright_ti4", 0)),
                    "confidence": row.get("confidence", ""),
                    "acq_date": row.get("acq_date", ""),
                    "acq_time": row.get("acq_time", ""),
                    "satellite": row.get("satellite", ""),
                    "frp": float(row.get("frp", 0)),
                })

                if len(hotspots) >= limit:
                    break

            except (ValueError, KeyError):
                continue

        print(f"[ML] Fetched {len(hotspots)} Nigeria hotspots for scanning.")
        return hotspots

    except Exception as e:
        print(f"[ML] Failed to fetch hotspots for scan: {e}")
        return []


# ═══════════════════════════════════════════════════════
# MANUAL PREDICTION ENDPOINTS
# ═══════════════════════════════════════════════════════

@router.post("/ml/predict")
async def predict_image(
    file: UploadFile = File(
        ..., description="Satellite image patch (JPEG/PNG)"
    ),
):
    """
    Run CampDetector inference on an uploaded satellite image patch.
    Returns classification (legal_activity vs suspicious_encampment)
    with confidence score and actionable recommendation.
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status": "unavailable",
                "message": "ML model not available.",
                "mock_result": {
                    "label": "legal_activity",
                    "confidence": 0.0,
                    "flag": False,
                    "class_id": 0,
                },
            }

        from PIL import Image
        import numpy as np
        from ml.preprocessor import preprocess_image

        # Read and validate uploaded file
        contents = await file.read()
        if len(contents) < 100:
            raise ValueError("Uploaded file is too small to be a valid image.")

        image = Image.open(io.BytesIO(contents)).convert("RGB")
        image_array = np.array(image)

        # Preprocess
        tensor = preprocess_image(image_array)
        if tensor is None:
            raise ValueError("Preprocessing failed — returned None.")

        # Predict with TTA for best accuracy
        result = detector.predict(tensor, use_tta=True)

        return {
            "status": "success",
            "filename": file.filename,
            "image_size": {
                "width": image.width,
                "height": image.height,
            },
            "result": result,
            "recommendation": _get_recommendation(result),
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/predict failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ml/predict-batch")
async def predict_batch(
    files: list[UploadFile] = File(
        ..., description="Multiple satellite image patches"
    ),
):
    """
    Run CampDetector on multiple uploaded images.
    Returns per-image results plus aggregate statistics.
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status": "unavailable",
                "message": "ML model not available.",
            }

        from PIL import Image
        import numpy as np
        from ml.preprocessor import preprocess_image

        results: list[dict[str, Any]] = []

        for upload_file in files:
            try:
                contents = await upload_file.read()
                image = Image.open(io.BytesIO(contents)).convert("RGB")
                image_array = np.array(image)
                tensor = preprocess_image(image_array)

                if tensor is not None:
                    prediction = detector.predict(tensor, use_tta=True)
                    results.append({
                        "filename": upload_file.filename,
                        "status": "success",
                        "result": prediction,
                        "recommendation": _get_recommendation(prediction),
                    })
                else:
                    results.append({
                        "filename": upload_file.filename,
                        "status": "error",
                        "error": "Preprocessing failed",
                    })

            except Exception as file_err:
                results.append({
                    "filename": upload_file.filename,
                    "status": "error",
                    "error": str(file_err),
                })

        # Aggregate stats
        successful = [r for r in results if r["status"] == "success"]
        flagged = sum(
            1 for r in successful
            if r.get("result", {}).get("flag", False)
        )
        critical = sum(
            1 for r in successful
            if r.get("recommendation", {}).get("level") == "CRITICAL"
        )

        return {
            "status": "success",
            "total": len(results),
            "analyzed": len(successful),
            "flagged": flagged,
            "critical": critical,
            "results": results,
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/predict-batch failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# COORDINATE-BASED ANALYSIS
# The KEY integration — analyze any lat/lon automatically
# ═══════════════════════════════════════════════════════

@router.post("/ml/analyze-location")
async def analyze_location(
    lat: float,
    lon: float,
    zoom: int = 17,
    use_tta: bool = True,
):
    """
    Analyze a specific coordinate by downloading satellite imagery
    and running the CampDetector model.

    This is the primary integration point used by:
    - Hotspot analysis (auto-scan fire locations)
    - Movement tracking (scan destination areas)
    - Manual investigation (analyst clicks a point on the map)
    - Alert verification (confirm suspicious activity)

    Args:
        lat:     Latitude of the location to analyze.
        lon:     Longitude of the location to analyze.
        zoom:    Satellite image zoom level (15-18, default 17).
        use_tta: Use test-time augmentation for higher accuracy.

    Returns:
        Classification result with recommendation.
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status": "unavailable",
                "message": "ML model not available.",
                "location": {"lat": lat, "lon": lon},
            }

        from ml.preprocessor import preprocess_image
        import numpy as np

        # Validate coordinates (Nigeria bounding box with margin)
        if not (-5.0 <= lat <= 20.0 and -5.0 <= lon <= 20.0):
            return {
                "status": "error",
                "message": (
                    f"Coordinates ({lat}, {lon}) are outside "
                    f"the supported region."
                ),
                "location": {"lat": lat, "lon": lon},
            }

        # Fetch satellite imagery for this location
        image = _fetch_satellite_tile(lat, lon, zoom=zoom)

        if image is None:
            return {
                "status": "error",
                "message": (
                    "Could not fetch satellite imagery for this location. "
                    "The tile server may be temporarily unavailable."
                ),
                "location": {"lat": lat, "lon": lon},
            }

        # Validate tile quality
        if not _is_valid_satellite_image(image):
            return {
                "status": "error",
                "message": (
                    "Downloaded satellite tile appears invalid "
                    "(blank, too dark, or cloud-covered). "
                    "Try a different zoom level."
                ),
                "location": {"lat": lat, "lon": lon},
            }

        # Preprocess and predict
        image_array = np.array(image)
        tensor = preprocess_image(image_array)

        if tensor is None:
            return {
                "status": "error",
                "message": "Image preprocessing failed.",
                "location": {"lat": lat, "lon": lon},
            }

        result = detector.predict(tensor, use_tta=use_tta)

        return {
            "status": "success",
            "location": {"lat": lat, "lon": lon},
            "zoom": zoom,
            "use_tta": use_tta,
            "result": result,
            "recommendation": _get_recommendation(result),
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/analyze-location failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# AUTOMATED HOTSPOT SCANNING
# FIRMS fire data → satellite tiles → ML classification
# ═══════════════════════════════════════════════════════

@router.post("/ml/scan-hotspots")
async def scan_hotspots(days: int = 1, limit: int = 50):
    """
    Automatically scan recent FIRMS hotspots with ML model.

    Pipeline for each hotspot:
      1. Get hotspot coordinates from FIRMS
      2. Download satellite imagery at that coordinate
      3. Run CampDetector inference
      4. Flag suspicious encampments
      5. Generate threat recommendations

    This connects:
      Fire/thermal data → Satellite imagery → ML classification
    into a single automated intelligence pipeline.

    Args:
        days:  Number of days of FIRMS data to scan (1-10).
        limit: Maximum number of hotspots to analyze (1-100).

    Returns:
        List of analyzed hotspots with predictions and recommendations.
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status": "unavailable",
                "message": "ML model not available.",
            }

        from ml.preprocessor import preprocess_image
        import numpy as np

        # Clamp parameters
        days = max(1, min(10, days))
        limit = max(1, min(100, limit))

        # Fetch recent hotspots from FIRMS
        hotspots_data = await _get_hotspots_for_scan(days, limit)

        if not hotspots_data:
            return {
                "status": "success",
                "message": (
                    "No hotspots found in Nigeria "
                    f"for the past {days} day(s)."
                ),
                "days": days,
                "scanned": 0,
                "flagged": 0,
                "results": [],
            }

        results: list[dict[str, Any]] = []
        flagged_count = 0
        critical_count = 0
        tile_failures = 0

        for idx, hotspot in enumerate(hotspots_data):
            lat = hotspot.get("latitude")
            lon = hotspot.get("longitude")

            if lat is None or lon is None:
                continue

            # Fetch satellite tile
            image = _fetch_satellite_tile(lat, lon, zoom=17)

            if image is None or not _is_valid_satellite_image(image):
                tile_failures += 1
                results.append({
                    "index": idx,
                    "location": {"lat": lat, "lon": lon},
                    "status": "tile_unavailable",
                    "hotspot_info": {
                        "brightness": hotspot.get("brightness"),
                        "confidence": hotspot.get("confidence"),
                        "acq_date": hotspot.get("acq_date"),
                        "satellite": hotspot.get("satellite"),
                    },
                })
                continue

            # Preprocess and predict
            image_array = np.array(image)
            tensor = preprocess_image(image_array)

            if tensor is None:
                continue

            prediction = detector.predict(tensor, use_tta=True)
            recommendation = _get_recommendation(prediction)

            is_flagged = prediction.get("flag", False)
            if is_flagged:
                flagged_count += 1
            if recommendation.get("level") == "CRITICAL":
                critical_count += 1

            results.append({
                "index": idx,
                "location": {"lat": lat, "lon": lon},
                "status": "analyzed",
                "prediction": prediction,
                "recommendation": recommendation,
                "hotspot_info": {
                    "brightness": hotspot.get("brightness"),
                    "confidence": hotspot.get("confidence"),
                    "acq_date": hotspot.get("acq_date"),
                    "acq_time": hotspot.get("acq_time"),
                    "satellite": hotspot.get("satellite"),
                    "frp": hotspot.get("frp"),
                },
            })

            # Rate limit: don't hammer the tile server
            time.sleep(0.3)

            # Progress logging for long scans
            if (idx + 1) % 10 == 0:
                print(
                    f"[ML] Scan progress: {idx + 1}/{len(hotspots_data)} "
                    f"hotspots analyzed, {flagged_count} flagged"
                )

        analyzed_count = sum(
            1 for r in results if r["status"] == "analyzed"
        )

        return {
            "status": "success",
            "days": days,
            "hotspots_found": len(hotspots_data),
            "scanned": analyzed_count,
            "tile_failures": tile_failures,
            "flagged": flagged_count,
            "critical": critical_count,
            "threat_ratio": (
                round(flagged_count / analyzed_count, 3)
                if analyzed_count > 0
                else 0.0
            ),
            "results": results,
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/scan-hotspots failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# AREA SCANNING
# Draw a rectangle → scan entire area for camps
# ═══════════════════════════════════════════════════════

@router.post("/ml/scan-area")
async def scan_area(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    grid_step: float = 0.01,
    zoom: int = 17,
):
    """
    Scan a rectangular area with a grid of satellite image patches.

    Use case: An analyst draws a rectangle on the map and says
    'scan this entire area for suspicious encampments.'

    Each grid point gets a satellite tile downloaded and analyzed.
    Only flagged (suspicious) locations are returned in detail
    to keep the response compact.

    Args:
        lat_min, lat_max: Latitude bounds of the scan area.
        lon_min, lon_max: Longitude bounds of the scan area.
        grid_step:        Distance between scan points in degrees.
                          0.01° ≈ 1.1 km at the equator.
        zoom:             Satellite tile zoom level (15-18).

    Returns:
        Summary stats and list of flagged locations.
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status": "unavailable",
                "message": "ML model not available.",
            }

        from ml.preprocessor import preprocess_image
        import numpy as np

        # Validate bounds
        if lat_min >= lat_max or lon_min >= lon_max:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid bounds: lat_min must be < lat_max "
                    "and lon_min must be < lon_max."
                ),
            )

        # Clamp grid_step
        grid_step = max(0.005, min(0.1, grid_step))

        # Generate grid points
        grid_points: list[tuple[float, float]] = []
        lat = lat_min
        while lat <= lat_max:
            lon = lon_min
            while lon <= lon_max:
                grid_points.append((round(lat, 6), round(lon, 6)))
                lon += grid_step
            lat += grid_step

        # Limit to prevent abuse / excessive tile downloads
        max_points = 100
        if len(grid_points) > max_points:
            return {
                "status": "error",
                "message": (
                    f"Area too large: {len(grid_points)} grid points "
                    f"would be generated. Maximum is {max_points}. "
                    f"Increase grid_step (currently {grid_step}) "
                    f"or reduce the scan area."
                ),
                "grid_points": len(grid_points),
                "max_allowed": max_points,
                "suggestion": round(
                    max(
                        (lat_max - lat_min),
                        (lon_max - lon_min),
                    )
                    / 10,
                    4,
                ),
            }

        flagged_locations: list[dict[str, Any]] = []
        scanned_count = 0
        flagged_count = 0
        critical_count = 0

        for idx, (lat, lon) in enumerate(grid_points):
            image = _fetch_satellite_tile(lat, lon, zoom=zoom)

            if image is None or not _is_valid_satellite_image(image):
                continue

            image_array = np.array(image)
            tensor = preprocess_image(image_array)

            if tensor is None:
                continue

            scanned_count += 1

            # Use TTA=False for area scans (speed over marginal accuracy)
            prediction = detector.predict(tensor, use_tta=False)

            is_flagged = prediction.get("flag", False)
            if is_flagged:
                flagged_count += 1
                recommendation = _get_recommendation(prediction)

                if recommendation.get("level") == "CRITICAL":
                    critical_count += 1

                # Only include flagged locations in response
                flagged_locations.append({
                    "location": {"lat": lat, "lon": lon},
                    "prediction": prediction,
                    "recommendation": recommendation,
                })

            # Rate limit
            time.sleep(0.3)

            # Progress logging
            if (idx + 1) % 20 == 0:
                print(
                    f"[ML] Area scan: {idx + 1}/{len(grid_points)} "
                    f"points, {flagged_count} flagged"
                )

        return {
            "status": "success",
            "area": {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lon_min": lon_min,
                "lon_max": lon_max,
            },
            "grid_step": grid_step,
            "grid_points_total": len(grid_points),
            "grid_points_scanned": scanned_count,
            "flagged": flagged_count,
            "critical": critical_count,
            "threat_ratio": (
                round(flagged_count / scanned_count, 3)
                if scanned_count > 0
                else 0.0
            ),
            "flagged_locations": flagged_locations,
        }

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /ml/scan-area failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# ML STATUS
# ═══════════════════════════════════════════════════════

@router.get("/ml/status")
def ml_status():
    """
    Check ML model availability, configuration, and capabilities.
    Used by the dashboard to show/hide ML features.
    """
    status: dict[str, Any] = {
        "torch_available": False,
        "model_loaded": False,
        "weights_found": False,
        "device": "cpu",
        "mode": os.getenv("EAGLEEYE_MODE", "dev"),
        "capabilities": {
            "predict": False,
            "analyze_location": False,
            "scan_hotspots": False,
            "scan_area": False,
        },
    }

    try:
        from ml.detector import TORCH_AVAILABLE, WEIGHTS_PATH

        status["torch_available"] = TORCH_AVAILABLE
        status["weights_found"] = WEIGHTS_PATH.exists()

        if TORCH_AVAILABLE:
            import torch

            status["device"] = (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
            status["cuda_available"] = torch.cuda.is_available()

            if torch.cuda.is_available():
                status["gpu_name"] = torch.cuda.get_device_name(0)

        detector = _get_detector()
        model_ready = detector is not None and detector.model is not None
        status["model_loaded"] = model_ready

        # All capabilities available if model is loaded
        if model_ready:
            status["capabilities"] = {
                "predict": True,
                "analyze_location": True,
                "scan_hotspots": True,
                "scan_area": True,
            }

    except Exception as e:
        status["error"] = str(e)

    return status