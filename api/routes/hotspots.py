"""
hotspots.py
────────────
API routes for thermal hotspot data with full analysis pipeline.
Includes movement detection and military intelligence alerts.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

# Store snapshots for movement comparison
SNAPSHOTS_DIR = Path(__file__).parent.parent.parent / "data" / "snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _save_snapshot(data: dict[str, Any], label: str) -> None:
    """Save a hotspot snapshot for later movement comparison."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "timestamp": datetime.utcnow().isoformat(),
        "label": label,
        "feature_count": len(data.get("features", [])),
        "clusters": _extract_clusters(data),
    }
    path = SNAPSHOTS_DIR / f"snapshot_{label}_{timestamp}.json"
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)

    # Keep only the last 50 snapshots
    snapshots = sorted(SNAPSHOTS_DIR.glob("snapshot_*.json"))
    for old in snapshots[:-50]:
        old.unlink(missing_ok=True)


def _extract_clusters(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract cluster centroids from hotspot data for movement tracking.
    Groups nearby hotspots into clusters.
    """
    features = data.get("features", [])
    if not features:
        return []

    # Group by state/region for simple clustering
    state_groups: dict[str, list[dict[str, float]]] = {}
    for f in features:
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        state = props.get("state", "Unknown")

        if state not in state_groups:
            state_groups[state] = []
        state_groups[state].append({
            "lat": coords[1] if len(coords) > 1 else 0,
            "lon": coords[0] if len(coords) > 0 else 0,
            "score": props.get("threat_score", 0),
        })

    clusters: list[dict[str, Any]] = []
    for state, points in state_groups.items():
        if not points:
            continue
        avg_lat = sum(p["lat"] for p in points) / len(points)
        avg_lon = sum(p["lon"] for p in points) / len(points)
        max_score = max(p["score"] for p in points)

        clusters.append({
            "state": state,
            "latitude": round(avg_lat, 4),
            "longitude": round(avg_lon, 4),
            "hotspot_count": len(points),
            "max_score": max_score,
        })

    return clusters


def _get_previous_snapshot() -> dict[str, Any] | None:
    """Load the most recent previous snapshot for comparison."""
    snapshots = sorted(SNAPSHOTS_DIR.glob("snapshot_current_*.json"))
    if len(snapshots) < 2:
        return None

    # Get second-to-last (previous)
    try:
        with open(snapshots[-2]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


@router.get("/hotspots")
def get_hotspots(
    days: int = Query(
        default=1, ge=1, le=10,
        description="Number of past days to fetch",
    ),
    country: str = Query(
        default="NGA",
        description="Country code (ISO 3166-1 alpha-3)",
    ),
    scored: bool = Query(
        default=True,
        description="Include threat scoring",
    ),
    regions: bool = Query(
        default=True,
        description="Include state/region classification",
    ),
    track_movement: bool = Query(
        default=True,
        description="Save snapshot for movement tracking",
    ),
) -> dict[str, Any]:
    """
    Fetch thermal hotspots from NASA FIRMS.
    Returns a scored, region-enriched GeoJSON FeatureCollection.
    """
    try:
        from ingestion.firms import fetch_hotspots
        data = fetch_hotspots(days=days, country=country)

        if regions:
            from analysis.region_classifier import enrich_with_regions
            data = enrich_with_regions(data)

        if scored:
            from analysis.anomaly_score import score_hotspots
            data = score_hotspots(data)

        # Save snapshot for movement tracking
        if track_movement:
            _save_snapshot(data, "current")

        return data

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots failed:\n{tb}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch hotspot data: {str(e)}",
        )


@router.get("/hotspots/summary")
def get_hotspots_summary(
    days: int = Query(default=1, ge=1, le=10),
) -> dict[str, Any]:
    """
    Returns a detailed summary of hotspots including threat breakdown.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        data = fetch_hotspots(days=days, country="NGA")
        data = enrich_with_regions(data)
        data = score_hotspots(data)

        features = data.get("features", [])

        high_conf = sum(
            1 for f in features
            if str(f["properties"].get("confidence", "")).upper()
            in ("H", "HIGH")
        )
        med_conf = sum(
            1 for f in features
            if str(f["properties"].get("confidence", "")).upper()
            in ("N", "NOMINAL")
        )
        low_conf = sum(
            1 for f in features
            if str(f["properties"].get("confidence", "")).upper()
            in ("L", "LOW")
        )

        critical = sum(
            1 for f in features
            if f["properties"].get("priority") == "CRITICAL"
        )
        high_pri = sum(
            1 for f in features
            if f["properties"].get("priority") == "HIGH"
        )
        elevated = sum(
            1 for f in features
            if f["properties"].get("priority") == "ELEVATED"
        )
        monitor = sum(
            1 for f in features
            if f["properties"].get("priority") == "MONITOR"
        )

        state_counts: dict[str, int] = {}
        for f in features:
            state = f["properties"].get("state", "Unknown")
            state_counts[state] = state_counts.get(state, 0) + 1
        top_states = sorted(
            state_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]

        zone_counts: dict[str, int] = {}
        for f in features:
            zone = f["properties"].get("red_zone", "Other")
            zone_counts[zone] = zone_counts.get(zone, 0) + 1

        tier_counts: dict[str, int] = {}
        for f in features:
            tier = f["properties"].get("threat_tier", "Unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        top_score = 0.0
        if features:
            top_score = max(
                f["properties"].get("threat_score", 0) for f in features
            )

        return {
            "total": len(features),
            "high_confidence": high_conf,
            "medium_confidence": med_conf,
            "low_confidence": low_conf,
            "days_queried": days,
            "threat_breakdown": {
                "critical": critical,
                "high": high_pri,
                "elevated": elevated,
                "monitor": monitor,
            },
            "top_threat_score": top_score,
            "top_states": [
                {"state": s, "count": c} for s, c in top_states
            ],
            "zone_breakdown": zone_counts,
            "threat_tier_breakdown": tier_counts,
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/summary failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/critical")
def get_critical_hotspots(
    days: int = Query(default=1, ge=1, le=10),
    min_score: float = Query(
        default=60.0, ge=0, le=100,
        description="Minimum threat score",
    ),
) -> dict[str, Any]:
    """
    Returns only high-priority hotspots above a given threat score.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        data = fetch_hotspots(days=days, country="NGA")
        data = enrich_with_regions(data)
        data = score_hotspots(data)

        critical_features = [
            f for f in data.get("features", [])
            if f["properties"].get("threat_score", 0) >= min_score
        ]

        return {
            "type": "FeatureCollection",
            "features": critical_features,
            "metadata": {
                "count": len(critical_features),
                "min_score_filter": min_score,
                "source": data.get(
                    "metadata", {}
                ).get("source", "NASA FIRMS"),
            },
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/critical failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/changes")
def get_hotspot_changes(
    current_days: int = Query(
        default=1, ge=1, le=5,
        description="Current snapshot days",
    ),
    previous_days: int = Query(
        default=2, ge=2, le=10,
        description="Previous snapshot days",
    ),
) -> dict[str, Any]:
    """
    Compare current hotspots vs. a previous period to detect
    new, persistent, and resolved hotspots.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from analysis.change_detection import detect_changes
        from analysis.region_classifier import enrich_with_regions

        current_raw = fetch_hotspots(days=current_days, country="NGA")
        previous_raw = fetch_hotspots(days=previous_days, country="NGA")

        current_data = enrich_with_regions(current_raw)
        previous_data = enrich_with_regions(previous_raw)

        changes = detect_changes(
            previous=previous_data, current=current_data
        )
        return changes

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/changes failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/movement")
def get_movement_analysis(
    days: int = Query(
        default=1, ge=1, le=5,
        description="Current snapshot days",
    ),
    compare_days: int = Query(
        default=3, ge=2, le=10,
        description="Previous period days to compare against",
    ),
) -> dict[str, Any]:
    """
    Detect hotspot cluster movement between two time periods.
    Identifies potential camp relocations and movement corridors.
    
    This is the core intelligence endpoint for tracking
    terrorist/bandit movement patterns.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        # Get current and previous data
        current_raw = fetch_hotspots(days=days, country="NGA")
        previous_raw = fetch_hotspots(days=compare_days, country="NGA")

        current_data = enrich_with_regions(score_hotspots(
            enrich_with_regions(current_raw)
        ))
        previous_data = enrich_with_regions(score_hotspots(
            enrich_with_regions(previous_raw)
        ))

        # Extract clusters
        current_clusters = _extract_clusters(current_data)
        previous_clusters = _extract_clusters(previous_data)

        # Detect movement
        from api.services.movement_tracker import MovementTracker
        tracker = MovementTracker()

        # Get state resolver function
        try:
            from analysis.region_classifier import get_state_from_coords
            state_fn = get_state_from_coords
        except ImportError:
            state_fn = None

        now = datetime.utcnow()
        movements = tracker.analyze_movement(
            clusters_before=previous_clusters,
            clusters_after=current_clusters,
            time_before=(
                now.replace(hour=0, minute=0)
                .__str__()
            ),
            time_after=now.isoformat(),
            get_state_fn=state_fn,
        )

        # Generate alerts for significant movements
        alerts = tracker.generate_alerts(movements, current_clusters)

        # Build response
        movement_data = [m.to_dict() for m in movements]
        alert_data = [a.to_dict() for a in alerts]

        # Classify movements by type
        relocations = [
            m for m in movement_data
            if m["classification"] == "camp_relocation"
        ]
        corridors = [
            m for m in movement_data
            if m["classification"] == "corridor"
        ]
        rapid = [
            m for m in movement_data
            if m["classification"] == "rapid_relocation"
        ]

        return {
            "analysis_time": now.isoformat(),
            "current_period_days": days,
            "comparison_period_days": compare_days,
            "current_clusters": len(current_clusters),
            "previous_clusters": len(previous_clusters),
            "movements_detected": len(movements),
            "alerts_generated": len(alerts),
            "summary": {
                "camp_relocations": len(relocations),
                "corridor_movements": len(corridors),
                "rapid_relocations": len(rapid),
                "critical_alerts": sum(
                    1 for a in alert_data
                    if a.get("priority") == "critical"
                ),
                "high_alerts": sum(
                    1 for a in alert_data
                    if a.get("priority") == "high"
                ),
            },
            "movements": movement_data,
            "alerts": alert_data,
            "clusters": {
                "current": current_clusters,
                "previous": previous_clusters,
            },
        }

    except ImportError as e:
        return {
            "error": f"Movement tracker not available: {e}",
            "hint": "Create api/services/movement_tracker.py",
            "movements": [],
            "alerts": [],
        }
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/movement failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/states")
def get_hotspots_by_state(
    days: int = Query(default=1, ge=1, le=10),
    state: str | None = Query(
        default=None,
        description="Filter by Nigerian state name",
    ),
) -> dict[str, Any]:
    """
    Returns hotspots filtered by Nigerian state.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        data = fetch_hotspots(days=days, country="NGA")
        data = enrich_with_regions(data)
        data = score_hotspots(data)

        features = data.get("features", [])

        if state:
            filtered = [
                f for f in features
                if f["properties"].get("state", "").lower()
                == state.lower()
            ]
            return {
                "type": "FeatureCollection",
                "features": filtered,
                "metadata": {
                    "count": len(filtered),
                    "state_filter": state,
                },
            }

        state_data: dict[str, dict[str, Any]] = {}
        for f in features:
            s = f["properties"].get("state", "Unknown")
            if s not in state_data:
                state_data[s] = {
                    "count": 0,
                    "high_confidence": 0,
                    "critical_threats": 0,
                    "max_score": 0,
                    "threat_tier": f["properties"].get(
                        "threat_tier", "Unknown"
                    ),
                }
            state_data[s]["count"] += 1
            if f["properties"].get("confidence") == "H":
                state_data[s]["high_confidence"] += 1
            if f["properties"].get("priority") == "CRITICAL":
                state_data[s]["critical_threats"] += 1
            score = f["properties"].get("threat_score", 0)
            if score > state_data[s]["max_score"]:
                state_data[s]["max_score"] = score

        sorted_states = dict(sorted(
            state_data.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        ))
        return {
            "states": sorted_states,
            "total_states_affected": len(sorted_states),
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/states failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/intel/brief")
def get_intelligence_brief(
    days: int = Query(default=1, ge=1, le=5),
) -> dict[str, Any]:
    """
    Generate a military-style intelligence brief.
    Combines hotspot data, movement analysis, and threat assessment
    into an actionable summary for security forces.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        data = fetch_hotspots(days=days, country="NGA")
        data = enrich_with_regions(data)
        data = score_hotspots(data)

        features = data.get("features", [])
        now = datetime.utcnow()

        # Threat summary
        critical_features = [
            f for f in features
            if f["properties"].get("priority") in ("CRITICAL", "HIGH")
        ]

        # Group critical threats by zone
        zone_threats: dict[str, list[dict[str, Any]]] = {}
        for f in critical_features:
            zone = f["properties"].get("red_zone", "Other")
            if zone not in zone_threats:
                zone_threats[zone] = []
            zone_threats[zone].append({
                "lat": f["geometry"]["coordinates"][1],
                "lon": f["geometry"]["coordinates"][0],
                "score": f["properties"].get("threat_score", 0),
                "state": f["properties"].get("state", "Unknown"),
                "priority": f["properties"].get("priority", "MONITOR"),
            })

        # Load recent alerts
        alerts_file = (
            Path(__file__).parent.parent.parent
            / "data" / "alerts" / "active_alerts.json"
        )
        recent_alerts: list[dict[str, Any]] = []
        if alerts_file.exists():
            try:
                with open(alerts_file) as f:
                    all_alerts = json.load(f)
                recent_alerts = [
                    a for a in all_alerts
                    if a.get("expires", "") >= now.isoformat()
                ][:10]
            except (json.JSONDecodeError, OSError):
                pass

        # Build the brief
        brief: dict[str, Any] = {
            "classification": "CONFIDENTIAL",
            "title": "EagleEye-Nigeria Threat Intelligence Brief",
            "generated": now.isoformat(),
            "period": f"Last {days} day(s)",
            "situation_overview": {
                "total_hotspots": len(features),
                "critical_threats": len(critical_features),
                "active_zones": len(zone_threats),
                "active_alerts": len(recent_alerts),
            },
            "priority_areas": [],
            "active_alerts": recent_alerts[:5],
            "recommended_actions": [],
        }

        # Priority areas
        for zone_name, threats in sorted(
            zone_threats.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        ):
            max_threat = max(threats, key=lambda t: t["score"])
            brief["priority_areas"].append({
                "zone": zone_name,
                "threat_count": len(threats),
                "highest_score": max_threat["score"],
                "primary_state": max_threat["state"],
                "coordinates": {
                    "lat": max_threat["lat"],
                    "lon": max_threat["lon"],
                },
                "assessment": _assess_zone_threat(
                    len(threats), max_threat["score"]
                ),
            })

        # Recommended actions
        if critical_features:
            brief["recommended_actions"].append(
                "Deploy aerial surveillance to critical threat zones"
            )
        if len(zone_threats) > 3:
            brief["recommended_actions"].append(
                "Increase patrol frequency across multiple active zones"
            )
        if recent_alerts:
            brief["recommended_actions"].append(
                "Review and action pending movement alerts"
            )
        if not brief["recommended_actions"]:
            brief["recommended_actions"].append(
                "Maintain routine monitoring — no elevated threats"
            )

        return brief

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/intel/brief failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


def _assess_zone_threat(count: int, max_score: float) -> str:
    """Generate a human-readable threat assessment."""
    if max_score >= 80 or count >= 10:
        return (
            "CRITICAL — Multiple high-confidence thermal signatures "
            "suggest active militant/bandit operations. "
            "Immediate reconnaissance recommended."
        )
    if max_score >= 60 or count >= 5:
        return (
            "HIGH — Significant thermal activity detected. "
            "Pattern consistent with camp activity. "
            "Enhanced monitoring recommended."
        )
    if max_score >= 40 or count >= 3:
        return (
            "ELEVATED — Moderate thermal activity. "
            "Could indicate agricultural burning or small settlements. "
            "Continue routine surveillance."
        )
    return (
        "MONITOR — Low-level activity. "
        "Likely routine agricultural or natural fires."
    )


@router.post("/hotspots/cache/clear")
def clear_cache() -> dict[str, Any]:
    """Clear the FIRMS data cache to force fresh API calls."""
    try:
        from ingestion.cache import firms_cache
        stats_before = firms_cache.stats()
        firms_cache.clear()
        return {
            "status": "cleared",
            "entries_removed": stats_before["active_entries"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/cache/stats")
def cache_stats() -> dict[str, Any]:
    """View current cache statistics."""
    try:
        from ingestion.cache import firms_cache
        return firms_cache.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))