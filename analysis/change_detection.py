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
import numpy as np
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
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
    metadata: Dict = field(default_factory=dict)

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


# ── Band Validation & Compatibility Helpers ───────────────────

def _validate_bands(
    bands: Dict[str, np.ndarray], label: str,
) -> bool:
    """
    Defense-in-depth check that band arrays contain usable data.
    Returns True if data looks valid, False otherwise.
    """
    if not bands:
        print(f"[CD] ✗ {label}: band dict is empty")
        return False

    for name, arr in bands.items():
        if arr is None or arr.size == 0:
            print(f"[CD] ✗ {label}: band {name} is None or empty")
            return False

        if name == "SCL":
            valid_pixels = int(np.sum(np.isin(arr, [4, 5, 6])))
            total = arr.size
            pct = 100.0 * valid_pixels / max(total, 1)
            if valid_pixels == 0:
                print(f"[CD] ✗ {label}: SCL has 0 valid land pixels")
                return False
            print(f"[CD]   {label} SCL: {valid_pixels}/{total} valid ({pct:.1f}%)")
            continue

        finite = np.isfinite(arr)
        finite_count = int(np.sum(finite))
        nonzero = int(np.sum(arr[finite] != 0)) if finite_count > 0 else 0

        if finite_count == 0 or nonzero == 0:
            print(
                f"[CD] ✗ {label}: band {name} has no usable pixels "
                f"(finite={finite_count}, nonzero={nonzero})"
            )
            return False

        print(
            f"[CD]   {label} {name}: OK "
            f"(range=[{np.nanmin(arr):.0f}, {np.nanmax(arr):.0f}], "
            f"nonzero={nonzero}/{arr.size})"
        )

    return True


def _check_scale_compatibility(
    bands_before: Dict[str, np.ndarray],
    bands_after: Dict[str, np.ndarray],
    threshold: float = 5.0,
) -> Tuple[bool, str]:
    """
    Check whether two band sets have compatible value ranges.

    If one is from the real Copernicus API (range 0–20000) and the other
    is synthetic (range 100–5000), the spatial patterns will be totally
    different and change detection will produce false positives.

    Returns (is_compatible, reason_string).
    """
    mismatches: List[str] = []

    for band in bands_before:
        if band == "SCL" or band not in bands_after:
            continue

        max_before = float(np.nanmax(bands_before[band]))
        max_after = float(np.nanmax(bands_after[band]))

        if min(max_before, max_after) <= 0:
            continue

        ratio = max(max_before, max_after) / min(max_before, max_after)

        if ratio > threshold:
            mismatches.append(
                f"{band}: max_before={max_before:.0f}, "
                f"max_after={max_after:.0f}, ratio={ratio:.1f}x"
            )

    if mismatches:
        reason = (
            f"Scale mismatch detected (threshold={threshold}x): "
            + "; ".join(mismatches)
        )
        return False, reason

    return True, "Scales compatible"


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

    # ── Date helpers ──────────────────────────────────────────

    @staticmethod
    def _clamp_date(date_str: str) -> str:
        """
        If a date string is in the future, clamp it to today.
        Prevents requesting satellite imagery that cannot exist.
        """
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            today = datetime.utcnow()
            if dt.date() > today.date():
                clamped = today.strftime("%Y-%m-%d")
                print(
                    f"[CD] ⚠ Date {date_str} is in the future — "
                    f"clamped to {clamped}"
                )
                return clamped
        except ValueError:
            pass
        return date_str

    @staticmethod
    def _ensure_date_order(
        date_before: str, date_after: str,
    ) -> Tuple[str, str]:
        """Ensure date_before < date_after, swap if needed."""
        try:
            dt_before = datetime.strptime(date_before, "%Y-%m-%d")
            dt_after = datetime.strptime(date_after, "%Y-%m-%d")
            if dt_before >= dt_after:
                print(
                    f"[CD] ⚠ date_before ({date_before}) >= date_after "
                    f"({date_after}) — swapping"
                )
                return date_after, date_before
        except ValueError:
            pass
        return date_before, date_after

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

        if bbox is None:
            raise ValueError(
                "Either a valid zone_name or bbox must be provided"
            )

        # ── Default date window: 14 days ending ~7 days ago ───
        now = datetime.utcnow()
        print(f"[CD] System UTC time: {now.isoformat()}")

        if date_after is None:
            dt_after = now - timedelta(days=7)
            date_after = dt_after.strftime("%Y-%m-%d")
        else:
            dt_after = datetime.strptime(date_after, "%Y-%m-%d")

        if date_before is None:
            date_before = (dt_after - timedelta(days=14)).strftime("%Y-%m-%d")

        # ── Clamp future dates & validate order ───────────────
        date_before = self._clamp_date(date_before)
        date_after = self._clamp_date(date_after)
        date_before, date_after = self._ensure_date_order(
            date_before, date_after,
        )

        print(
            f"[CD] Final dates: before={date_before}, after={date_after}, "
            f"zone={zone_name}, bbox={bbox}, index={index}"
        )

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
            metadata={
                "system_time": now.isoformat() + "Z",
                "original_date_before": date_before,
                "original_date_after": date_after,
            },
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
            "Starting change detection: zone=%s bbox=%s %s→%s index=%s "
            "bands=%s",
            zone_name, bbox, date_before, date_after, index, required_bands,
        )

        try:
            # ── Fetch imagery ─────────────────────────────────
            print(f"[CD] Fetching bands for date_before={date_before}...")
            bands_before = self.sentinel2.get_bands(
                bbox=bbox, date=date_before, bands=required_bands,
            )

            print(f"[CD] Fetching bands for date_after={date_after}...")
            bands_after = self.sentinel2.get_bands(
                bbox=bbox, date=date_after, bands=required_bands,
            )

            # ── Validate band data (defense in depth) ─────────
            before_valid = _validate_bands(
                bands_before, f"BEFORE ({date_before})",
            )
            after_valid = _validate_bands(
                bands_after, f"AFTER ({date_after})",
            )

            if not before_valid or not after_valid:
                job.status = "failed"
                job.error = (
                    f"Band data validation failed: "
                    f"before_valid={before_valid}, "
                    f"after_valid={after_valid}. "
                    f"This may indicate an issue with the data source."
                )
                logger.error(
                    "Band validation failed for job %s: before=%s, after=%s",
                    job_id, before_valid, after_valid,
                )
                return job

            # ── Check scale compatibility ─────────────────────
            # If one date got real API data and the other got
            # synthetic, the spatial patterns are completely
            # different and change detection would be meaningless.
            # Force both to synthetic for a consistent comparison.

            compatible, reason = _check_scale_compatibility(
                bands_before, bands_after,
            )

            if not compatible:
                print(f"[CD] ⚠ {reason}")
                print(
                    "[CD]   Mixed real/synthetic data detected — "
                    "re-fetching both as synthetic for consistency"
                )
                job.metadata["scale_mismatch_detected"] = True
                job.metadata["scale_mismatch_reason"] = reason
                job.metadata["data_source"] = "synthetic (forced)"

                bands_before = self.sentinel2.get_bands(
                    bbox=bbox,
                    date=date_before,
                    bands=required_bands,
                    force_synthetic=True,
                )
                bands_after = self.sentinel2.get_bands(
                    bbox=bbox,
                    date=date_after,
                    bands=required_bands,
                    force_synthetic=True,
                )

                # Re-validate the forced synthetic data
                bv = _validate_bands(
                    bands_before, f"BEFORE-SYNTH ({date_before})",
                )
                av = _validate_bands(
                    bands_after, f"AFTER-SYNTH ({date_after})",
                )
                if not bv or not av:
                    job.status = "failed"
                    job.error = (
                        "Forced synthetic data also failed validation"
                    )
                    return job

                # Verify they are now compatible
                compat2, _ = _check_scale_compatibility(
                    bands_before, bands_after,
                )
                print(
                    f"[CD] ✓ After re-fetch: "
                    f"scales compatible = {compat2}"
                )
            else:
                print("[CD] ✓ Scale compatibility check passed")
                job.metadata["scale_mismatch_detected"] = False
                job.metadata["data_source"] = "consistent"

            # ── Analyse ───────────────────────────────────────
            print(f"[CD] Running vegetation analysis (index={index})...")
            analyzer = self._VegetationAnalyzer(
                vegetation_zone=vegetation_zone,
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

                        # ── Enrich events with state/LGA (local, instant) ─
            enriched_events = []
            for e in events:
                event_dict = e.to_dict()
                try:
                    from utils.geocoding import reverse_geocode
                    loc = reverse_geocode(
                        e.latitude, e.longitude,
                        use_nominatim=False,  # Local only — instant, no rate limits
                    )
                    event_dict["state"] = loc.state
                    event_dict["lga"] = loc.lga
                    event_dict["nearest_town"] = loc.nearest_town
                    event_dict["nearest_town_distance_km"] = loc.nearest_town_distance_km
                    event_dict["nearest_town_direction"] = loc.nearest_town_direction
                    event_dict["geo_zone"] = loc.geo_zone
                    event_dict["state_capital"] = loc.state_capital
                    event_dict["coords_dms"] = loc.coords_dms
                    event_dict["google_maps_url"] = loc.google_maps_url
                    event_dict["operational_description"] = loc.operational_description
                    event_dict["additional_context"] = loc.additional_context
                    event_dict["location"] = loc.to_dict()
                    print(
                        f"[CD]   Event {e.event_id[:20]}... → "
                        f"{loc.state}, {loc.lga}, near {loc.nearest_town}"
                    )
                except Exception as loc_err:
                    print(
                        f"[CD] ⚠ Location enrichment failed for "
                        f"({e.latitude}, {e.longitude}): {loc_err}"
                    )
                    import traceback
                    traceback.print_exc()
                    # Fallback: provide empty fields so frontend
                    # doesn't show "undefined"
                    event_dict.setdefault("state", "Unknown")
                    event_dict.setdefault("lga", "Unknown LGA")
                    event_dict.setdefault("nearest_town", "")
                    event_dict.setdefault("nearest_town_distance_km", 0)
                    event_dict.setdefault("nearest_town_direction", "")
                    event_dict.setdefault("geo_zone", "")
                    event_dict.setdefault("state_capital", "")
                    event_dict.setdefault("coords_dms", "")
                    event_dict.setdefault("google_maps_url",
                        f"https://www.google.com/maps/search/?api=1&query={e.latitude},{e.longitude}"
                    )
                    event_dict.setdefault("operational_description", "")
                    event_dict.setdefault("additional_context", "")
                    event_dict.setdefault("location", {})

                enriched_events.append(event_dict)

            job.events = enriched_events
            job.snapshot_before = snap_before.to_dict()
            job.snapshot_after = snap_after.to_dict()

            print(
                f"[CD] ✓ Change detection complete: job={job_id}, "
                f"events={len(events)}"
            )
            logger.info(
                "Change detection complete: job=%s events=%d",
                job_id, len(events),
            )

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            print(f"[CD] ✗ Change detection failed: {e}")
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
        results: List[ChangeDetectionJob] = []
        total = len(self.monitoring_zones)

        for i, zone_name in enumerate(self.monitoring_zones, 1):
            print(f"[CD] Processing zone {i}/{total}: {zone_name}")
            logger.info("Processing zone: %s", zone_name)
            try:
                job = self.run(
                    zone_name=zone_name,
                    date_before=date_before,
                    date_after=date_after,
                    index=index,
                )
                results.append(job)
                print(
                    f"[CD]   → {zone_name}: status={job.status}, "
                    f"events={job.events_found}"
                )
            except Exception as e:
                logger.error("Zone %s failed: %s", zone_name, e)
                print(f"[CD]   → {zone_name}: FAILED — {e}")

        completed = sum(1 for j in results if j.status == "completed")
        failed = sum(1 for j in results if j.status == "failed")
        total_events = sum(j.events_found for j in results)
        print(
            f"[CD] Batch complete: {completed} succeeded, {failed} failed, "
            f"{total_events} total events"
        )
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

    def clear_jobs(self) -> int:
        """Clear all stored jobs. Returns count of removed jobs."""
        count = len(_job_store)
        _job_store.clear()
        print(f"[CD] Cleared {count} jobs from store")
        return count

    # ── Cross-source correlation ──────────────────────────────

    def correlate_with_hotspots(
        self,
        change_events: List[Dict],
        hotspots_geojson: Dict,
        radius_km: float = 10.0,
    ) -> List[Dict]:
        """
        Enrich vegetation change events with nearby FIRMS thermal hotspots.
        """
        hotspot_pts: List[Dict] = []
        for f in hotspots_geojson.get("features", []):
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                hotspot_pts.append({
                    "lon": coords[0],
                    "lat": coords[1],
                    "props": f.get("properties", {}),
                })

        enriched: List[Dict] = []
        for evt in change_events:
            evt_lat = evt.get("latitude", 0)
            evt_lon = evt.get("longitude", 0)

            nearby: List[Dict] = []
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
        """
        acled_pts: List[Dict] = []
        for f in acled_geojson.get("features", []):
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                acled_pts.append({
                    "lon": coords[0],
                    "lat": coords[1],
                    "props": f.get("properties", {}),
                })

        enriched: List[Dict] = []
        for evt in change_events:
            evt_lat = evt.get("latitude", 0)
            evt_lon = evt.get("longitude", 0)

            nearby: List[Dict] = []
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
        if "SCL" not in bands:
            bands.append("SCL")
        if "B12" not in bands:
            bands.append("B12")
        return bands


# ══════════════════════════════════════════════════════════════
# HOTSPOT CHANGE DETECTION (separate from Sentinel-2 pipeline)
# ══════════════════════════════════════════════════════════════

def _hotspot_haversine(
    lat1: float, lon1: float, lat2: float, lon2: float,
) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 6371.0 * 2 * asin(sqrt(a))


def _get_feature_coords(
    feature: Dict,
) -> tuple[float, float]:
    """Extract (lat, lon) from a GeoJSON feature."""
    coords = feature.get("geometry", {}).get("coordinates", [0, 0])
    lon = float(coords[0]) if len(coords) > 0 else 0.0
    lat = float(coords[1]) if len(coords) > 1 else 0.0
    return lat, lon


def detect_changes(
    previous: Dict,
    current: Dict,
    match_radius_km: float = 2.0,
) -> Dict:
    """
    Compare two GeoJSON FeatureCollections of hotspot data.

    Classifies each hotspot as:
      - new: Present in current but not in previous
      - persistent: Present in both (within match_radius_km)
      - resolved: Present in previous but not in current
    """
    prev_features: List[Dict] = previous.get("features", [])
    curr_features: List[Dict] = current.get("features", [])

    prev_matched: set[int] = set()
    curr_matched: set[int] = set()

    persistent: List[Dict] = []

    for ci, c_feat in enumerate(curr_features):
        c_lat, c_lon = _get_feature_coords(c_feat)

        for pi, p_feat in enumerate(prev_features):
            if pi in prev_matched:
                continue

            p_lat, p_lon = _get_feature_coords(p_feat)
            dist = _hotspot_haversine(c_lat, c_lon, p_lat, p_lon)

            if dist <= match_radius_km:
                curr_score = float(
                    c_feat.get("properties", {}).get("threat_score", 0)
                )
                prev_score = float(
                    p_feat.get("properties", {}).get("threat_score", 0)
                )

                merged_props = {
                    **c_feat.get("properties", {}),
                    "change_type": "persistent",
                    "days_active": "2+",
                    "previous_score": prev_score,
                    "score_change": round(curr_score - prev_score, 2),
                }

                persistent.append({
                    "type": "Feature",
                    "geometry": c_feat.get("geometry", {}),
                    "properties": merged_props,
                })

                prev_matched.add(pi)
                curr_matched.add(ci)
                break

    new_hotspots: List[Dict] = []
    for ci, c_feat in enumerate(curr_features):
        if ci not in curr_matched:
            props = {
                **c_feat.get("properties", {}),
                "change_type": "new",
            }
            new_hotspots.append({
                "type": "Feature",
                "geometry": c_feat.get("geometry", {}),
                "properties": props,
            })

    resolved: List[Dict] = []
    for pi, p_feat in enumerate(prev_features):
        if pi not in prev_matched:
            props = {
                **p_feat.get("properties", {}),
                "change_type": "resolved",
            }
            resolved.append({
                "type": "Feature",
                "geometry": p_feat.get("geometry", {}),
                "properties": props,
            })

    escalating: List[Dict] = [
        f for f in persistent
        if f["properties"].get("score_change", 0) > 5
    ]

    return {
        "type": "FeatureCollection",
        "features": new_hotspots + persistent + resolved,
        "summary": {
            "total_current": len(curr_features),
            "total_previous": len(prev_features),
            "new": len(new_hotspots),
            "persistent": len(persistent),
            "resolved": len(resolved),
            "escalating": len(escalating),
            "match_radius_km": match_radius_km,
        },
        "new_hotspots": {
            "type": "FeatureCollection",
            "features": new_hotspots,
        },
        "persistent_hotspots": {
            "type": "FeatureCollection",
            "features": persistent,
        },
        "resolved_hotspots": {
            "type": "FeatureCollection",
            "features": resolved,
        },
        "escalating_hotspots": {
            "type": "FeatureCollection",
            "features": escalating,
        },
    }