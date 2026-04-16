"""
api/routes/sentinel2.py
───────────────────────
Sentinel-2 vegetation change detection API endpoints.

Provides:
  GET  /sentinel2/health                   Subsystem health
  GET  /sentinel2/zones                    List monitoring zones
  POST /sentinel2/scenes/search            Search Copernicus catalogue
  POST /sentinel2/snapshot                 Single-date vegetation stats
  POST /sentinel2/change-detection         Run change detection
  POST /sentinel2/change-detection/all     Run all monitoring zones
  GET  /sentinel2/jobs                     List analysis jobs
  GET  /sentinel2/jobs/{job_id}            Get job by ID
  GET  /sentinel2/events                   Query events across jobs
  GET  /sentinel2/events/geojson           Export as GeoJSON
"""

import os
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from api.models.sentinel2 import (
    SceneSearchRequest,
    ChangeDetectionRequest,
    VegetationSnapshotRequest,
    ChangeDetectionJobResponse,
    ChangeEventResponse,
    VegetationSnapshotResponse,
    SceneResponse,
    MonitoringZoneResponse,
    Sentinel2HealthResponse,
    SeverityEnum,
)

logger = logging.getLogger("eagleeye.api.sentinel2")
router = APIRouter()


# ── Lazy pipeline singleton ───────────────────────────────────

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from analysis.change_detection import ChangeDetectionPipeline
        _pipeline = ChangeDetectionPipeline()
    return _pipeline


# ── Health ────────────────────────────────────────────────────

@router.get(
    "/sentinel2/health",
    response_model=Sentinel2HealthResponse,
    summary="Sentinel-2 subsystem health",
)
def sentinel2_health():
    from ingestion.sentinel2 import MONITORING_ZONES
    from analysis.vegetation import VEGETATION_THRESHOLDS, VegetationIndex

    creds_set = bool(
        os.getenv("COPERNICUS_USER") and os.getenv("COPERNICUS_PASSWORD")
    )
    cache_dir = Path("./data/sentinel2_cache")
    cached_files = (
        len(list(cache_dir.glob("*.npz")))
        if cache_dir.exists()
        else 0
    )

    return Sentinel2HealthResponse(
        sentinel2_configured=creds_set,
        credentials_set=creds_set,
        cache_dir_exists=cache_dir.exists(),
        cached_files=cached_files,
        monitoring_zones=len(MONITORING_ZONES),
        available_indices=[idx.value for idx in VegetationIndex],
        vegetation_zones=list(VEGETATION_THRESHOLDS.keys()),
    )


# ── Monitoring Zones ──────────────────────────────────────────

@router.get(
    "/sentinel2/zones",
    response_model=List[MonitoringZoneResponse],
    summary="List monitoring zones",
    description=(
        "Returns all pre-defined monitoring zones with bounding boxes "
        "and risk levels."
    ),
)
def list_monitoring_zones():
    from ingestion.sentinel2 import MONITORING_ZONES

    return [
        MonitoringZoneResponse(
            zone_id=zone_id,
            name=cfg["name"],
            bbox=cfg["bbox"],
            risk_level=cfg["risk_level"],
            description=cfg["description"],
        )
        for zone_id, cfg in MONITORING_ZONES.items()
    ]


# ── Scene Search ──────────────────────────────────────────────

@router.post(
    "/sentinel2/scenes/search",
    response_model=List[SceneResponse],
    summary="Search Sentinel-2 scenes",
    description=(
        "Query the Copernicus Data Space catalogue for available "
        "Sentinel-2 L2A scenes over a given area and date range."
    ),
)
def search_scenes(request: SceneSearchRequest):
    try:
        from ingestion.sentinel2 import get_sentinel2_client

        client = get_sentinel2_client()
        scenes = client.search_scenes(
            bbox=request.bbox.to_list(),
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            max_cloud_cover=request.max_cloud_cover,
            max_results=request.max_results,
        )
        return [
            SceneResponse(
                scene_id=s.scene_id,
                datetime=s.datetime,
                cloud_cover=s.cloud_cover,
                bbox=s.bbox,
                tile_id=s.tile_id,
                product_type=s.product_type,
                processing_level=s.processing_level,
            )
            for s in scenes
        ]
    except Exception as e:
        logger.error("Scene search failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Scene search failed: {e}"
        )


# ── Vegetation Snapshot ───────────────────────────────────────

@router.post(
    "/sentinel2/snapshot",
    response_model=VegetationSnapshotResponse,
    summary="Single-date vegetation snapshot",
    description=(
        "Compute vegetation index statistics (mean, median, std, "
        "histogram) for a given area and date."
    ),
)
def vegetation_snapshot(request: VegetationSnapshotRequest):
    try:
        from ingestion.sentinel2 import get_sentinel2_client
        from analysis.vegetation import VegetationAnalyzer, VegetationIndex

        client = get_sentinel2_client()
        veg_index = VegetationIndex(request.index.value)
        analyzer = VegetationAnalyzer(
            vegetation_zone=request.vegetation_zone,
        )

        band_map = {
            "ndvi": ["B04", "B08", "SCL"],
            "evi":  ["B02", "B04", "B08", "SCL"],
            "savi": ["B04", "B08", "SCL"],
            "nbr":  ["B08", "B12", "SCL"],
            "ndmi": ["B08", "B11", "SCL"],
        }
        bands_needed = band_map.get(
            request.index.value, ["B04", "B08", "SCL"]
        )

        bands = client.get_bands(
            bbox=request.bbox.to_list(),
            date=request.target_date.isoformat(),
            bands=bands_needed,
        )

        snapshot = analyzer.compute_snapshot(
            bands=bands,
            date=request.target_date.isoformat(),
            bbox=request.bbox.to_list(),
            index=veg_index,
        )

        return VegetationSnapshotResponse(**snapshot.to_dict())

    except Exception as e:
        logger.error("Vegetation snapshot failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"Snapshot failed: {e}"
        )


# ── Change Detection ──────────────────────────────────────────

@router.post(
    "/sentinel2/change-detection",
    response_model=ChangeDetectionJobResponse,
    summary="Run vegetation change detection",
    description=(
        "Compare vegetation indices between two dates to identify "
        "clearings, burn scars, and anomalies. Optionally cross-reference "
        "with FIRMS hotspots and ACLED conflict data."
    ),
)
def run_change_detection(request: ChangeDetectionRequest):
    pipeline = _get_pipeline()
    try:
        bbox = request.bbox.to_list() if request.bbox else None
        job = pipeline.run(
            zone_name=request.zone_name,
            bbox=bbox,
            date_before=(
                request.date_before.isoformat()
                if request.date_before else None
            ),
            date_after=(
                request.date_after.isoformat()
                if request.date_after else None
            ),
            index=request.index.value,
            vegetation_zone=request.vegetation_zone,
            max_cloud_cover=request.max_cloud_cover,
        )

        if job.status == "failed":
            raise HTTPException(
                status_code=502,
                detail=job.error or "Analysis failed",
            )

        # ── Optional cross-source correlation ─────────────────
        if job.events and (
            request.correlate_hotspots or request.correlate_acled
        ):
            enriched = job.events

            if request.correlate_hotspots:
                try:
                    from ingestion.firms import fetch_hotspots
                    hotspots = fetch_hotspots(days=30)
                    enriched = pipeline.correlate_with_hotspots(
                        enriched, hotspots, radius_km=10.0,
                    )
                except Exception as err:
                    logger.warning(
                        "Hotspot correlation failed: %s", err,
                    )

            if request.correlate_acled:
                try:
                    from ingestion.acled import fetch_acled_events
                    acled = fetch_acled_events(days=60)
                    enriched = pipeline.correlate_with_acled(
                        enriched, acled, radius_km=25.0,
                    )
                except Exception as err:
                    logger.warning(
                        "ACLED correlation failed: %s", err,
                    )

            job.events = enriched

        return ChangeDetectionJobResponse(**job.to_dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Change detection failed: %s", e, exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Internal error: {e}",
        )


@router.post(
    "/sentinel2/change-detection/all-zones",
    response_model=List[ChangeDetectionJobResponse],
    summary="Run change detection on all monitoring zones",
    description=(
        "Process every pre-defined monitoring zone in a single request."
    ),
)
def run_all_zones(
    date_before: Optional[str] = Query(
        None, description="YYYY-MM-DD",
    ),
    date_after: Optional[str] = Query(
        None, description="YYYY-MM-DD",
    ),
    index: str = Query("ndvi"),
):
    pipeline = _get_pipeline()
    jobs = pipeline.run_all_zones(
        date_before=date_before,
        date_after=date_after,
        index=index,
    )
    return [ChangeDetectionJobResponse(**j.to_dict()) for j in jobs]


# ── Job Management ────────────────────────────────────────────

@router.get(
    "/sentinel2/jobs",
    response_model=List[ChangeDetectionJobResponse],
    summary="List change detection jobs",
)
def list_jobs(
    status: Optional[str] = Query(
        None,
        description="Filter: pending|running|completed|failed",
    ),
    limit: int = Query(50, ge=1, le=200),
):
    pipeline = _get_pipeline()
    jobs = pipeline.list_jobs(status=status, limit=limit)
    return [ChangeDetectionJobResponse(**j.to_dict()) for j in jobs]


@router.get(
    "/sentinel2/jobs/{job_id}",
    response_model=ChangeDetectionJobResponse,
    summary="Get change detection job by ID",
)
def get_job(job_id: str):
    pipeline = _get_pipeline()
    job = pipeline.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Job '{job_id}' not found",
        )
    return ChangeDetectionJobResponse(**job.to_dict())


# ── Event Queries ─────────────────────────────────────────────

@router.get(
    "/sentinel2/events",
    response_model=List[ChangeEventResponse],
    summary="Query change events across all completed jobs",
    description=(
        "Aggregate and filter vegetation change events from all "
        "completed analysis jobs."
    ),
)
def query_events(
    severity: Optional[SeverityEnum] = Query(None),
    classification: Optional[str] = Query(
        None, description="clearing|burn_scar|regrowth",
    ),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    min_area_ha: float = Query(0.0, ge=0.0),
    zone_name: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    pipeline = _get_pipeline()
    completed = pipeline.list_jobs(status="completed", limit=500)

    all_events = []
    for job in completed:
        if zone_name and job.zone_name != zone_name:
            continue
        for evt in job.events:
            all_events.append(evt)

    # Filters
    filtered = all_events
    if severity:
        filtered = [
            e for e in filtered
            if e.get("severity") == severity.value
        ]
    if classification:
        filtered = [
            e for e in filtered
            if e.get("classification") == classification
        ]
    filtered = [
        e for e in filtered
        if e.get("confidence", 0) >= min_confidence
    ]
    filtered = [
        e for e in filtered
        if e.get("area_hectares", 0) >= min_area_ha
    ]

    # Sort by confidence desc
    filtered.sort(
        key=lambda e: e.get("confidence", 0), reverse=True,
    )

    return [ChangeEventResponse(**e) for e in filtered[:limit]]


# ── GeoJSON Export ────────────────────────────────────────────

@router.get(
    "/sentinel2/events/geojson",
    summary="Export change events as GeoJSON",
    description=(
        "Returns detected vegetation change events as a GeoJSON "
        "FeatureCollection for direct map overlay."
    ),
)
def events_geojson(
    severity: Optional[SeverityEnum] = Query(None),
    classification: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    pipeline = _get_pipeline()
    completed = pipeline.list_jobs(status="completed", limit=500)

    features = []
    for job in completed:
        for evt in job.events:
            if severity and evt.get("severity") != severity.value:
                continue
            if classification and evt.get("classification") != classification:
                continue
            if evt.get("confidence", 0) < min_confidence:
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        evt["longitude"],
                        evt["latitude"],
                    ],
                },
                "properties": {
                    k: v
                    for k, v in evt.items()
                    if k not in ("latitude", "longitude")
                },
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "source": (
                "EagleEye-Nigeria Sentinel-2 Change Detection"
            ),
        },
    }