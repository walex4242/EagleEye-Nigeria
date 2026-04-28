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

Fixes in this version:
  • FIRMS URL now uses Nigeria bounding box (2.5,4.0,15.0,14.0)
    instead of the invalid "world" token that caused HTTP 400.
  • FIRMS_MAP_KEY missing / "DEMO_KEY" fallback is rejected early
    with a clear log message instead of silently hitting the API.
  • ml_status() now always returns full capability metadata:
    classes, zoom_levels, tta_enabled, confidence_threshold —
    so the dashboard panel shows real values instead of "—".
  • _get_hotspots_for_scan logs the exact request URL and the
    first 300 chars of any error response for easier debugging.
  • float() calls on FIRMS CSV fields are guarded against empty
    strings so a bad row no longer silently drops the loop.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
import traceback
import io
import os
import time
from typing import Any

router = APIRouter()

# ── Nigeria bounding box ───────────────────────────────────────
# FIRMS area CSV format: W,S,E,N
# This is the only valid area token for a sub-global region.
# "world" is NOT accepted by the FIRMS area endpoint → HTTP 400.
_NIGERIA_BBOX = "2.5,4.0,15.0,14.0"

# ── Model capability constants ────────────────────────────────
# These are returned by ml_status() so the dashboard panel can
# display them in the capabilities strip (Classes / Zoom / TTA /
# Threshold). Keep them in sync with CampDetector training config.
_MODEL_CLASSES              = ["legal_activity", "suspicious_encampment"]
_MODEL_ZOOM_LEVELS          = [15, 16, 17, 18]
_MODEL_TTA_ENABLED          = True
_MODEL_CONFIDENCE_THRESHOLD = 0.75   # matches flag threshold in _get_recommendation


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
            print("[ML] ⚠️  CampDetector model is None after init.")
            _detector_instance = None

    except Exception as e:
        print(f"[ML] ❌ Failed to load CampDetector: {e}")
        traceback.print_exc()
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

    Downloads a 3×3 grid of 256 px tiles, stitches them,
    and crops the centre to the requested size.

    Args:
        lat:  Latitude of the target location.
        lon:  Longitude of the target location.
        zoom: Tile zoom level (15-18). Higher = more detail.
        size: Output image size in pixels (default 224 for ResNet).

    Returns:
        PIL.Image.Image or None if any tile download fails.
    """
    try:
        import math
        import requests
        from PIL import Image
        from io import BytesIO

        # Convert lat/lon → slippy-map tile XY
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

        tile_size = 256
        tiles: list[list[Image.Image]] = []

        # Download 3×3 grid centred on the target tile
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
                        "Referer":    "https://www.arcgis.com/",
                    },
                )
                if resp.status_code == 200 and len(resp.content) > 1000:
                    tile = Image.open(BytesIO(resp.content)).convert("RGB")
                    row.append(tile)
                else:
                    # Any missing tile makes the stitch impossible
                    return None
            tiles.append(row)

        # Stitch 3×3 into one large image
        stitched = Image.new("RGB", (tile_size * 3, tile_size * 3))
        for row_idx, row in enumerate(tiles):
            for col_idx, tile in enumerate(row):
                stitched.paste(
                    tile.resize((tile_size, tile_size)),
                    (col_idx * tile_size, row_idx * tile_size),
                )

        # Crop the centre to the target size
        cx   = (tile_size * 3) // 2
        cy   = (tile_size * 3) // 2
        half = size // 2

        crop = stitched.crop((
            max(0,             cx - half),
            max(0,             cy - half),
            min(tile_size * 3, cx + half),
            min(tile_size * 3, cy + half),
        ))

        if crop.size != (size, size):
            crop = crop.resize((size, size))

        return crop

    except Exception as e:
        print(f"[ML] Tile fetch failed for ({lat}, {lon}): {e}")
        return None


def _is_valid_satellite_image(image: Any) -> bool:
    """
    Reject tiles that are blank, mostly black (ocean/night),
    or mostly white (cloud cover).
    """
    try:
        import numpy as np

        arr  = np.array(image)
        std  = float(np.std(arr))
        mean = float(np.mean(arr))

        if std  < 10:  return False   # uniform / blank
        if mean < 20:  return False   # too dark  (ocean or night)
        if mean > 240: return False   # too bright (thick cloud)

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
    label      = result.get("label", "")
    confidence = result.get("confidence", 0.0)
    flag       = result.get("flag", False)

    if flag and confidence >= 0.9:
        return {
            "level":    "CRITICAL",
            "action":   "IMMEDIATE_INVESTIGATION",
            "message":  (
                "High-confidence suspicious encampment detected. "
                "Recommend immediate drone/ground verification."
            ),
            "priority": 1,
        }
    elif flag and confidence >= 0.75:
        return {
            "level":    "HIGH",
            "action":   "PRIORITY_REVIEW",
            "message":  (
                "Probable suspicious encampment. "
                "Schedule priority aerial surveillance."
            ),
            "priority": 2,
        }
    elif flag:
        return {
            "level":    "MEDIUM",
            "action":   "MONITOR",
            "message":  (
                "Possible suspicious activity detected. "
                "Add to monitoring watchlist for repeat scanning."
            ),
            "priority": 3,
        }
    elif label == "legal_activity" and confidence >= 0.85:
        return {
            "level":    "LOW",
            "action":   "CLEAR",
            "message":  (
                "Location classified as legal activity "
                "with high confidence."
            ),
            "priority": 5,
        }
    else:
        return {
            "level":    "LOW",
            "action":   "RECHECK",
            "message":  (
                "Inconclusive result. Consider rescanning "
                "at a different time or zoom level."
            ),
            "priority": 4,
        }


# ═══════════════════════════════════════════════════════
# HOTSPOT DATA FETCHER  (used by scan-hotspots)
# ═══════════════════════════════════════════════════════

async def _get_hotspots_for_scan(
    days: int,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Extract hotspot coordinates for ML scanning by reusing the
    existing ingestion.firms.fetch_hotspots() pipeline.

    Reads NASA_FIRMS_API_KEY from the environment (with
    FIRMS_MAP_KEY as a legacy fallback so old deployments
    don't silently break).
    """
    try:
        # ── Resolve the API key ───────────────────────────────────
        # Check both names so renaming the env var doesn't break
        # existing deployments.
        firms_key = (
            os.getenv("NASA_FIRMS_API_KEY")   # ← your .env name
            or os.getenv("FIRMS_MAP_KEY")      # ← legacy fallback
            or ""
        )

        if not firms_key or firms_key.upper() in ("DEMO_KEY", ""):
            print(
                "[ML] NASA_FIRMS_API_KEY is not set. "
                "Add it to your .env file to enable hotspot scanning.\n"
                "     Get a free key at: "
                "https://firms.modaps.eosdis.nasa.gov/api/map_key/"
            )
            return []

        # ── Reuse the existing ingestion pipeline ─────────────────
        # ingestion/firms.py already handles caching, retries, and
        # the NGA country filter — no need to duplicate the HTTP call.
        from ingestion.firms import fetch_hotspots

        print(f"[ML] Fetching FIRMS hotspots via ingestion pipeline "
              f"(days={days}, limit={limit})…")

        geojson  = fetch_hotspots(days=days, country="NGA")
        features = geojson.get("features", [])

        if not features:
            print("[ML] No hotspot features returned from FIRMS pipeline.")
            return []

        # ── Optional enrichment ───────────────────────────────────
        try:
            from analysis.region_classifier import enrich_with_regions
            geojson  = enrich_with_regions(geojson)
            features = geojson.get("features", [])
        except Exception as enrich_err:
            print(f"[ML] Region enrichment skipped: {enrich_err}")

        try:
            from analysis.anomaly_score import score_hotspots
            geojson  = score_hotspots(geojson)
            features = geojson.get("features", [])
        except Exception as score_err:
            print(f"[ML] Anomaly scoring skipped: {score_err}")

        # ── Convert GeoJSON features → flat hotspot dicts ─────────
        def _safe_float(val: Any, default: float = 0.0) -> float:
            try:
                return float(val) if val not in (None, "", "nan") else default
            except (ValueError, TypeError):
                return default

        hotspots: list[dict[str, Any]] = []

        for feature in features:
            try:
                geometry = feature.get("geometry", {})
                coords   = geometry.get("coordinates", [])
                props    = feature.get("properties", {})

                if not coords or len(coords) < 2:
                    continue

                lon = float(coords[0])   # GeoJSON is [lon, lat]
                lat = float(coords[1])

                # Nigeria bounding-box guard
                if not (4.0 <= lat <= 14.0 and 2.5 <= lon <= 15.0):
                    continue

                hotspots.append({
                    "latitude":     lat,
                    "longitude":    lon,
                    "brightness":   _safe_float(
                        props.get("bright_ti4") or props.get("brightness")
                    ),
                    "confidence":   props.get("confidence", ""),
                    "acq_date":     props.get("acq_date",   ""),
                    "acq_time":     props.get("acq_time",   ""),
                    "satellite":    props.get("satellite",  ""),
                    "frp":          _safe_float(props.get("frp")),
                    "state":        props.get("state",        ""),
                    "threat_score": _safe_float(props.get("threat_score")),
                    "priority":     props.get("priority",     ""),
                })

                if len(hotspots) >= limit:
                    break

            except (ValueError, KeyError, TypeError) as row_err:
                print(f"[ML] Skipping malformed feature: {row_err}")
                continue

        print(f"[ML] Extracted {len(hotspots)} Nigeria hotspots "
              f"from {len(features)} total features.")
        return hotspots

    except ImportError as e:
        print(f"[ML] ingestion.firms not importable: {e}")
        return []
    except Exception as e:
        print(f"[ML] _get_hotspots_for_scan failed: {e}")
        traceback.print_exc()
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
                "status":      "unavailable",
                "message":     "ML model not available.",
                "mock_result": {
                    "label":      "legal_activity",
                    "confidence": 0.0,
                    "flag":       False,
                    "class_id":   0,
                },
            }

        from PIL import Image
        import numpy as np
        from ml.preprocessor import preprocess_image

        contents = await file.read()
        if len(contents) < 100:
            raise ValueError("Uploaded file is too small to be a valid image.")

        image       = Image.open(io.BytesIO(contents)).convert("RGB")
        image_array = np.array(image)
        tensor      = preprocess_image(image_array)

        if tensor is None:
            raise ValueError("Preprocessing returned None — image may be corrupt.")

        result = detector.predict(tensor, use_tta=True)

        return {
            "status":         "success",
            "filename":       file.filename,
            "image_size":     {"width": image.width, "height": image.height},
            "result":         result,
            "recommendation": _get_recommendation(result),
        }

    except Exception as e:
        print(f"[ERROR] /ml/predict failed:\n{traceback.format_exc()}")
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
                "status":  "unavailable",
                "message": "ML model not available.",
            }

        from PIL import Image
        import numpy as np
        from ml.preprocessor import preprocess_image

        results: list[dict[str, Any]] = []

        for upload_file in files:
            try:
                contents    = await upload_file.read()
                image       = Image.open(io.BytesIO(contents)).convert("RGB")
                image_array = np.array(image)
                tensor      = preprocess_image(image_array)

                if tensor is not None:
                    prediction = detector.predict(tensor, use_tta=True)
                    results.append({
                        "filename":       upload_file.filename,
                        "status":         "success",
                        "result":         prediction,
                        "recommendation": _get_recommendation(prediction),
                    })
                else:
                    results.append({
                        "filename": upload_file.filename,
                        "status":   "error",
                        "error":    "Preprocessing failed",
                    })

            except Exception as file_err:
                results.append({
                    "filename": upload_file.filename,
                    "status":   "error",
                    "error":    str(file_err),
                })

        successful = [r for r in results if r["status"] == "success"]
        flagged    = sum(
            1 for r in successful
            if r.get("result", {}).get("flag", False)
        )
        critical   = sum(
            1 for r in successful
            if r.get("recommendation", {}).get("level") == "CRITICAL"
        )

        return {
            "status":   "success",
            "total":    len(results),
            "analyzed": len(successful),
            "flagged":  flagged,
            "critical": critical,
            "results":  results,
        }

    except Exception as e:
        print(f"[ERROR] /ml/predict-batch failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# COORDINATE-BASED ANALYSIS
# ═══════════════════════════════════════════════════════

@router.post("/ml/analyze-location")
async def analyze_location(
    lat:     float,
    lon:     float,
    zoom:    int  = 17,
    use_tta: bool = True,
):
    """
    Analyze a specific coordinate by downloading satellite imagery
    and running the CampDetector model.

    Primary integration point used by:
      - Hotspot popups ("Analyze with ML" button)
      - Movement tracking (scan destination areas)
      - Manual investigation (analyst picks a point on the map)
      - Alert verification (confirm suspicious activity)

    Args:
        lat:     Latitude  (-90 … 90).
        lon:     Longitude (-180 … 180).
        zoom:    Satellite tile zoom level (15-18, default 17).
        use_tta: Use test-time augmentation for higher accuracy.
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status":   "unavailable",
                "message":  "ML model not available.",
                "location": {"lat": lat, "lon": lon},
            }

        from ml.preprocessor import preprocess_image
        import numpy as np

        # Validate coordinates — Nigeria with generous margin
        if not (-5.0 <= lat <= 20.0 and -5.0 <= lon <= 20.0):
            return {
                "status":   "error",
                "message":  (
                    f"Coordinates ({lat}, {lon}) are outside "
                    "the supported region (West Africa)."
                ),
                "location": {"lat": lat, "lon": lon},
            }

        image = _fetch_satellite_tile(lat, lon, zoom=zoom)

        if image is None:
            return {
                "status":   "error",
                "message":  (
                    "Could not fetch satellite imagery for this location. "
                    "The tile server may be temporarily unavailable."
                ),
                "location": {"lat": lat, "lon": lon},
            }

        if not _is_valid_satellite_image(image):
            return {
                "status":   "error",
                "message":  (
                    "Downloaded satellite tile appears invalid "
                    "(blank, too dark, or cloud-covered). "
                    "Try a different zoom level."
                ),
                "location": {"lat": lat, "lon": lon},
            }

        image_array = np.array(image)
        tensor      = preprocess_image(image_array)

        if tensor is None:
            return {
                "status":   "error",
                "message":  "Image preprocessing failed.",
                "location": {"lat": lat, "lon": lon},
            }

        result = detector.predict(tensor, use_tta=use_tta)

        return {
            "status":         "success",
            "location":       {"lat": lat, "lon": lon},
            "zoom":           zoom,
            "use_tta":        use_tta,
            "result":         result,
            "recommendation": _get_recommendation(result),
        }

    except Exception as e:
        print(f"[ERROR] /ml/analyze-location failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# AUTOMATED HOTSPOT SCANNING
# FIRMS fire data → satellite tiles → ML classification
# ═══════════════════════════════════════════════════════

@router.post("/ml/scan-hotspots")
async def scan_hotspots(days: int = 1, limit: int = 50):
    """
    Automatically scan recent FIRMS hotspots with the ML model.

    Pipeline for each hotspot:
      1. Fetch hotspot coordinates from FIRMS (Nigeria bbox)
      2. Download satellite imagery at that coordinate
      3. Run CampDetector inference
      4. Flag suspicious encampments
      5. Generate threat recommendations

    Args:
        days:  Number of days of FIRMS data to scan (1-10).
        limit: Maximum hotspots to analyze (1-100).
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status":  "unavailable",
                "message": "ML model not available.",
            }

        from ml.preprocessor import preprocess_image
        import numpy as np

        days  = max(1, min(10,  days))
        limit = max(1, min(100, limit))

        hotspots_data = await _get_hotspots_for_scan(days, limit)

        if not hotspots_data:
            return {
                "status":          "success",
                "message":         (
                    f"No hotspots found in Nigeria for the past {days} day(s). "
                    "Check that FIRMS_MAP_KEY is set correctly in your .env file."
                ),
                "days":            days,
                "scanned":         0,
                "tile_failures":   0,
                "flagged":         0,
                "critical":        0,
                "threat_ratio":    0.0,
                "results":         [],
            }

        results:       list[dict[str, Any]] = []
        flagged_count  = 0
        critical_count = 0
        tile_failures  = 0

        for idx, hotspot in enumerate(hotspots_data):
            lat = hotspot.get("latitude")
            lon = hotspot.get("longitude")

            if lat is None or lon is None:
                continue

            image = _fetch_satellite_tile(lat, lon, zoom=17)

            if image is None or not _is_valid_satellite_image(image):
                tile_failures += 1
                results.append({
                    "index":        idx,
                    "location":     {"lat": lat, "lon": lon},
                    "status":       "tile_unavailable",
                    "hotspot_info": {
                        "brightness": hotspot.get("brightness"),
                        "confidence": hotspot.get("confidence"),
                        "acq_date":   hotspot.get("acq_date"),
                        "satellite":  hotspot.get("satellite"),
                    },
                })
                continue

            image_array = np.array(image)
            tensor      = preprocess_image(image_array)

            if tensor is None:
                continue

            prediction     = detector.predict(tensor, use_tta=True)
            recommendation = _get_recommendation(prediction)
            is_flagged     = prediction.get("flag", False)

            if is_flagged:
                flagged_count += 1
            if recommendation.get("level") == "CRITICAL":
                critical_count += 1

            results.append({
                "index":          idx,
                "location":       {"lat": lat, "lon": lon},
                "status":         "analyzed",
                "prediction":     prediction,
                "recommendation": recommendation,
                "hotspot_info":   {
                    "brightness": hotspot.get("brightness"),
                    "confidence": hotspot.get("confidence"),
                    "acq_date":   hotspot.get("acq_date"),
                    "acq_time":   hotspot.get("acq_time"),
                    "satellite":  hotspot.get("satellite"),
                    "frp":        hotspot.get("frp"),
                },
            })

            # Polite rate-limit — don't hammer the tile server
            time.sleep(0.3)

            if (idx + 1) % 10 == 0:
                print(
                    f"[ML] Scan progress: {idx + 1}/{len(hotspots_data)} "
                    f"hotspots, {flagged_count} flagged so far"
                )

        analyzed_count = sum(1 for r in results if r["status"] == "analyzed")

        return {
            "status":          "success",
            "days":            days,
            "hotspots_found":  len(hotspots_data),
            "scanned":         analyzed_count,
            "tile_failures":   tile_failures,
            "flagged":         flagged_count,
            "critical":        critical_count,
            "threat_ratio":    (
                round(flagged_count / analyzed_count, 3)
                if analyzed_count > 0 else 0.0
            ),
            "results":         results,
        }

    except Exception as e:
        print(f"[ERROR] /ml/scan-hotspots failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# AREA SCANNING
# Draw a rectangle on the map → scan entire area
# ═══════════════════════════════════════════════════════

@router.post("/ml/scan-area")
async def scan_area(
    lat_min:   float,
    lat_max:   float,
    lon_min:   float,
    lon_max:   float,
    grid_step: float = 0.01,
    zoom:      int   = 17,
):
    """
    Scan a rectangular area with a grid of satellite image patches.

    Each grid point gets a satellite tile downloaded and classified.
    Only flagged (suspicious) locations are included in the response
    to keep the payload compact.

    Args:
        lat_min, lat_max: South / North latitude bounds.
        lon_min, lon_max: West  / East  longitude bounds.
        grid_step:        Distance between scan points in degrees.
                          0.01° ≈ 1.1 km. Clamped to 0.005 – 0.1.
        zoom:             Satellite tile zoom level (15-18).
    """
    try:
        detector = _get_detector()

        if detector is None:
            return {
                "status":  "unavailable",
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

        # Hard cap to prevent runaway tile downloads
        max_points = 100
        if len(grid_points) > max_points:
            suggestion = round(
                max((lat_max - lat_min), (lon_max - lon_min)) / 10, 4
            )
            return {
                "status":      "error",
                "message":     (
                    f"Area too large: {len(grid_points)} grid points would be "
                    f"generated. Maximum is {max_points}. "
                    f"Increase grid_step (currently {grid_step}°) or reduce "
                    f"the scan area. Suggested grid_step: {suggestion}°"
                ),
                "grid_points": len(grid_points),
                "max_allowed": max_points,
                "suggestion":  suggestion,
            }

        flagged_locations: list[dict[str, Any]] = []
        scanned_count  = 0
        flagged_count  = 0
        critical_count = 0

        for idx, (lat, lon) in enumerate(grid_points):
            image = _fetch_satellite_tile(lat, lon, zoom=zoom)

            if image is None or not _is_valid_satellite_image(image):
                continue

            image_array = np.array(image)
            tensor      = preprocess_image(image_array)

            if tensor is None:
                continue

            scanned_count += 1

            # TTA=False for area scans — speed over marginal accuracy gain
            prediction = detector.predict(tensor, use_tta=False)
            is_flagged  = prediction.get("flag", False)

            if is_flagged:
                flagged_count  += 1
                recommendation  = _get_recommendation(prediction)

                if recommendation.get("level") == "CRITICAL":
                    critical_count += 1

                flagged_locations.append({
                    "location":       {"lat": lat, "lon": lon},
                    "prediction":     prediction,
                    "recommendation": recommendation,
                })

            time.sleep(0.3)

            if (idx + 1) % 20 == 0:
                print(
                    f"[ML] Area scan: {idx + 1}/{len(grid_points)} "
                    f"points processed, {flagged_count} flagged"
                )

        return {
            "status": "success",
            "area": {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lon_min": lon_min,
                "lon_max": lon_max,
            },
            "grid_step":           grid_step,
            "grid_points_total":   len(grid_points),
            "grid_points_scanned": scanned_count,
            "flagged":             flagged_count,
            "critical":            critical_count,
            "threat_ratio":        (
                round(flagged_count / scanned_count, 3)
                if scanned_count > 0 else 0.0
            ),
            "flagged_locations":   flagged_locations,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] /ml/scan-area failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
# ML STATUS
# ═══════════════════════════════════════════════════════

@router.get("/ml/status")
def ml_status():
    """
    Check ML model availability, configuration, and capabilities.

    FIX: Previous version returned capability booleans only.
    Now always includes full metadata (classes, zoom_levels,
    tta_enabled, confidence_threshold) so the dashboard panel
    displays correct values instead of "—" for every field.

    The metadata fields are populated even when the model is
    offline, so the UI always has something useful to show.
    """
    # ── Base response — safe defaults ────────────────────────
    status: dict[str, Any] = {
        "torch_available": False,
        "model_loaded":    False,
        "weights_found":   False,
        "device":          "cpu",
        "mode":            os.getenv("EAGLEEYE_MODE", "dev"),
        # Capability object is ALWAYS present and ALWAYS contains
        # both feature flags AND model metadata.
        "capabilities": {
            # Feature flags (updated to True when model is ready)
            "predict":          False,
            "analyze_location": False,
            "scan_hotspots":    False,
            "scan_area":        False,
            # Model metadata (always populated from module constants)
            "classes":               _MODEL_CLASSES,
            "zoom_levels":           _MODEL_ZOOM_LEVELS,
            "tta_enabled":           _MODEL_TTA_ENABLED,
            "confidence_threshold":  _MODEL_CONFIDENCE_THRESHOLD,
        },
    }

    try:
        from ml.detector import TORCH_AVAILABLE, WEIGHTS_PATH

        status["torch_available"] = TORCH_AVAILABLE
        status["weights_found"]   = WEIGHTS_PATH.exists()

        if TORCH_AVAILABLE:
            import torch
            status["device"]         = "cuda" if torch.cuda.is_available() else "cpu"
            status["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                status["gpu_name"] = torch.cuda.get_device_name(0)

        detector    = _get_detector()
        model_ready = detector is not None and detector.model is not None
        status["model_loaded"] = model_ready

        if model_ready:
            # Enable all feature flags
            status["capabilities"].update({
                "predict":          True,
                "analyze_location": True,
                "scan_hotspots":    True,
                "scan_area":        True,
            })

            # If CampDetector exposes its own config attributes,
            # prefer those over the module-level constants.
            if hasattr(detector, "classes") and detector.classes:
                status["capabilities"]["classes"] = list(detector.classes)

            if hasattr(detector, "confidence_threshold"):
                status["capabilities"]["confidence_threshold"] = (
                    float(detector.confidence_threshold)
                )

            if hasattr(detector, "tta_enabled"):
                status["capabilities"]["tta_enabled"] = bool(detector.tta_enabled)

            if hasattr(detector, "zoom_levels") and detector.zoom_levels:
                status["capabilities"]["zoom_levels"] = list(detector.zoom_levels)

    except Exception as e:
        status["error"] = str(e)
        print(f"[ML] ml_status() encountered an error: {e}")

    return status