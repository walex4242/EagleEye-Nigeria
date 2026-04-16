"""
analysis/change_detection.py
────────────────────────────
Orchestrates the full Sentinel-2 change detection pipeline:
  scene search → band download → index computation → change analysis → alerts

Also provides cross-source correlation between vegetation change events,
FIRMS thermal hotspots, and ACLED conflict events.
"""

from __future__ import annotations
import logging
import hashlib
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("eagleeye.change_detection")


# ── Job Dataclass ─────────────────────────────────────────────

@dataclass
class ChangeDetectionJob:
    """Tracks a single change detection analysis run."""
    job_id: str
    zone_name: str
    bbox: List[float]
    date_before: str
    date_after: str
    vegetation_zone: str
    index: str
    status: str = "pending"       # pending | running | completed | failed
    created_at: str = ""
    completed_at: Optional[str] = None
    events_found: int = 0
    error: Optional[str] = None
    events: List[Dict] = field(default_factory=list)
    snapshot_before: Optional[Dict] = None
    snapshot_after: Optional[Dict] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict:
        return asdict(self)


# ── In-memory job store (swap with DB for production) ─────────

_job_store: Dict[str, ChangeDetectionJob] = {}

# Zone → vegetation type inference
_ZONE_VEG_MAP = {
    "zamfara_corridor": "sudan_savanna",
    "sambisa_forest":   "sudan_savanna",
    "niger_delta":      "mangrove",
    "kaduna_southern":  "guinea_savanna",
    "benue_valley":     "guinea_savanna",
}


# ── Haversine ─────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return R * 2 * asin(sqrt(a))


# ── Pipeline ──────────────────────────────────────────────────

class ChangeDetectionPipeline:
    """
    End-to-end change detection pipeline.

    Usage::

        pipeline = ChangeDetectionPipeline()
        job = pipeline.run(
            zone_name="zamfara_corridor",
            date_before="2024-01-01",
            date_after="2024-01-15",
        )
    """

    def __init__(self):
        from ingestion.sentinel2 import get_sentinel2_client, MONITORING_ZONES
        from analysis.vegetation import VegetationAnalyzer, VegetationIndex

        self.sentinel2 = get_sentinel2_client()
        self.monitoring_zones = MONITORING_ZONES
        self._VegetationAnalyzer = VegetationAnalyzer
        self._VegetationIndex = VegetationIndex

    # ── Primary execution ─────────────────────────────────────

    def run(
        self,
        zone_name: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        date_before: Optional[str] = None,
        date_after: Optional[str] = None,
        index: str = "ndvi",
        vegetation_zone: str = "default",
        max_cloud_cover: float = 30.0,
    ) -> ChangeDetectionJob:
        """Execute the full change detection pipeline for a single area."""

        # ── Resolve bounding box ──────────────────────────────
        if zone_name and zone_name in self.monitoring_zones:
            zone_cfg = self.monitoring_zones[zone_name]
            bbox = zone_cfg["bbox"]
            if vegetation_zone == "default":
                vegetation_zone = _ZONE_VEG_MAP.get(zone_name, "default")
        elif bbox is None:
            raise ValueError("Either zone_name or bbox must be provided")

        # ── Default date window: 14 days ending today ─────────
        if date_after is None:
            date_after = datetime.utcnow().strftime("%Y-%m-%d")
        if date_before is None:
            dt_after = datetime.strptime(date_after, "%Y-%m-%d")
            date_before = (dt_after - timedelta(days=14)).strftime("%Y-%m-%d")

        # ── Create job ────────────────────────────────────────
        job_id = hashlib.md5(
            f"{bbox}-{date_before}-{date_after}-{index}-"
            f"{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:12]

        job = ChangeDetectionJob(
            job_id=job_id,
            zone_name=zone_name or "custom",
            bbox=bbox,
            date_before=date_before,
            date_after=date_after,
            vegetation_zone=vegetation_zone,
            index=index,
            status="running",
        )
        _job_store[job_id] = job

        # ── Validate index ────────────────────────────────────
        try:
            veg_index = self._VegetationIndex(index)
        except ValueError:
            job.status = "failed"
            job.error = f"Unsupported vegetation index: {index}"
            return job

        required_bands = self._bands_for_index(veg_index)

        logger.info(
            "Starting change detection: zone=%s bbox=%s %s→%s index=%s",
            zone_name, bbox, date_before, date_after, index,
        )

        try:
            # ── Fetch imagery ─────────────────────────────────
            logger.info("Fetching bands for date_before=%s", date_before)
            bands_before = self.sentinel2.get_bands(
                bbox=bbox, date=date_before, bands=required_bands,
            )

            logger.info("Fetching bands for date_after=%s", date_after)
            bands_after = self.sentinel2.get_bands(
                bbox=bbox, date=date_after, bands=required_bands,
            )

            # ── Analyse ───────────────────────────────────────
            analyzer = self._VegetationAnalyzer(
                vegetation_zone=vegetation_zone
            )

            snap_before = analyzer.compute_snapshot(
                bands_before, date_before, bbox, veg_index,
            )
            snap_after = analyzer.compute_snapshot(
                bands_after, date_after, bbox, veg_index,
            )

            events = analyzer.detect_changes(
                bands_before=bands_before,
                bands_after=bands_after,
                date_before=date_before,
                date_after=date_after,
                bbox=bbox,
                index=veg_index,
            )

            # ── Finalise ──────────────────────────────────────
            job.status = "completed"
            job.completed_at = datetime.utcnow().isoformat() + "Z"
            job.events_found = len(events)
            job.events = [e.to_dict() for e in events]
            job.snapshot_before = snap_before.to_dict()
            job.snapshot_after = snap_after.to_dict()

            logger.info(
                "Change detection complete: job=%s events=%d",
                job_id, len(events),
            )

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            logger.error("Change detection failed: %s", e, exc_info=True)

        return job

    # ── Batch processing ──────────────────────────────────────

    def run_all_zones(
        self,
        date_before: Optional[str] = None,
        date_after: Optional[str] = None,
        index: str = "ndvi",
    ) -> List[ChangeDetectionJob]:
        """Run change detection on every pre-defined monitoring zone."""
        results = []
        for zone_name in self.monitoring_zones:
            logger.info("Processing zone: %s", zone_name)
            try:
                job = self.run(
                    zone_name=zone_name,
                    date_before=date_before,
                    date_after=date_after,
                    index=index,
                )
                results.append(job)
            except Exception as e:
                logger.error("Zone %s failed: %s", zone_name, e)
        return results

    # ── Job management ────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[ChangeDetectionJob]:
        return _job_store.get(job_id)

    def list_jobs(
        self, status: Optional[str] = None, limit: int = 50,
    ) -> List[ChangeDetectionJob]:
        jobs = list(_job_store.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    # ── Cross-source correlation ──────────────────────────────

    def correlate_with_hotspots(
        self,
        change_events: List[Dict],
        hotspots_geojson: Dict,
        radius_km: float = 10.0,
    ) -> List[Dict]:
        """
        Enrich vegetation change events with nearby FIRMS thermal hotspots.
        Adds 'nearby_hotspots', 'nearest_hotspots', 'thermal_correlation'.
        """
        hotspot_pts = []
        for f in hotspots_geojson.get("features", []):
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                hotspot_pts.append({
                    "lon": coords[0],
                    "lat": coords[1],
                    "props": f.get("properties", {}),
                })

        enriched = []
        for evt in change_events:
            evt_lat = evt.get("latitude", 0)
            evt_lon = evt.get("longitude", 0)

            nearby = []
            for hp in hotspot_pts:
                dist = _haversine(evt_lat, evt_lon, hp["lat"], hp["lon"])
                if dist <= radius_km:
                    nearby.append({
                        "distance_km": round(dist, 1),
                        "brightness": hp["props"].get("brightness", 0),
                        "confidence": hp["props"].get("confidence", ""),
                        "acq_date": hp["props"].get("acq_date", ""),
                        "frp": hp["props"].get("frp", ""),
                    })

            nearby.sort(key=lambda x: x["distance_km"])
            enriched.append({
                **evt,
                "nearby_hotspots": len(nearby),
                "nearest_hotspots": nearby[:5],
                "thermal_correlation": len(nearby) > 0,
            })

        return enriched

    def correlate_with_acled(
        self,
        change_events: List[Dict],
        acled_geojson: Dict,
        radius_km: float = 25.0,
    ) -> List[Dict]:
        """
        Enrich vegetation change events with nearby ACLED conflict events.
        Adds 'nearby_conflicts', 'nearby_fatalities', 'conflict_correlation'.
        """
        acled_pts = []
        for f in acled_geojson.get("features", []):
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                acled_pts.append({
                    "lon": coords[0],
                    "lat": coords[1],
                    "props": f.get("properties", {}),
                })

        enriched = []
        for evt in change_events:
            evt_lat = evt.get("latitude", 0)
            evt_lon = evt.get("longitude", 0)

            nearby = []
            for ap in acled_pts:
                dist = _haversine(evt_lat, evt_lon, ap["lat"], ap["lon"])
                if dist <= radius_km:
                    nearby.append({
                        "distance_km": round(dist, 1),
                        "event_type": ap["props"].get("event_type", ""),
                        "event_date": ap["props"].get("event_date", ""),
                        "fatalities": ap["props"].get("fatalities", 0),
                        "location": ap["props"].get("location", ""),
                    })

            nearby.sort(key=lambda x: x["distance_km"])
            total_fatalities = sum(e.get("fatalities", 0) for e in nearby)

            enriched.append({
                **evt,
                "nearby_conflicts": len(nearby),
                "nearby_fatalities": total_fatalities,
                "nearest_conflicts": nearby[:5],
                "conflict_correlation": len(nearby) > 0,
            })

        return enriched

    # ── Internal helpers ──────────────────────────────────────

    def _bands_for_index(self, index) -> List[str]:
        """Return Sentinel-2 bands needed for a given index + cloud mask."""
        band_map = {
            "ndvi": ["B04", "B08"],
            "evi":  ["B02", "B04", "B08"],
            "savi": ["B04", "B08"],
            "nbr":  ["B08", "B12"],
            "ndmi": ["B08", "B11"],
        }
        bands = list(band_map.get(index.value, ["B04", "B08"]))
        # Always include SCL for cloud masking
        if "SCL" not in bands:
            bands.append("SCL")
        # Always include B12 for burn scar cross-check
        if "B12" not in bands:
            bands.append("B12")
        return bands