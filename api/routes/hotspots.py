"""
hotspots.py
────────────
API routes for thermal hotspot data with full analysis pipeline.
"""

from fastapi import APIRouter, HTTPException, Query
import traceback

router = APIRouter()


@router.get("/hotspots")
def get_hotspots(
    days: int = Query(default=1, ge=1, le=10, description="Number of past days to fetch"),
    country: str = Query(default="NGA", description="Country code (ISO 3166-1 alpha-3)"),
    scored: bool = Query(default=True, description="Include threat scoring"),
    regions: bool = Query(default=True, description="Include state/region classification"),
):
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
):
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

        high_conf = sum(1 for f in features if str(f["properties"].get("confidence", "")).upper() in ("H", "HIGH"))
        med_conf = sum(1 for f in features if str(f["properties"].get("confidence", "")).upper() in ("N", "NOMINAL"))
        low_conf = sum(1 for f in features if str(f["properties"].get("confidence", "")).upper() in ("L", "LOW"))

        critical = sum(1 for f in features if f["properties"].get("priority") == "CRITICAL")
        high_pri = sum(1 for f in features if f["properties"].get("priority") == "HIGH")
        elevated = sum(1 for f in features if f["properties"].get("priority") == "ELEVATED")
        monitor = sum(1 for f in features if f["properties"].get("priority") == "MONITOR")

        state_counts: dict[str, int] = {}
        for f in features:
            state = f["properties"].get("state", "Unknown")
            state_counts[state] = state_counts.get(state, 0) + 1
        top_states = sorted(state_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        zone_counts: dict[str, int] = {}
        for f in features:
            zone = f["properties"].get("red_zone", "Other")
            zone_counts[zone] = zone_counts.get(zone, 0) + 1

        tier_counts: dict[str, int] = {}
        for f in features:
            tier = f["properties"].get("threat_tier", "Unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        top_score = 0
        if features:
            top_score = max(f["properties"].get("threat_score", 0) for f in features)

        summary = {
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
            "top_states": [{"state": s, "count": c} for s, c in top_states],
            "zone_breakdown": zone_counts,
            "threat_tier_breakdown": tier_counts,
        }
        return summary

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/summary failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/critical")
def get_critical_hotspots(
    days: int = Query(default=1, ge=1, le=10),
    min_score: float = Query(default=60.0, ge=0, le=100, description="Minimum threat score"),
):
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
                "source": data.get("metadata", {}).get("source", "NASA FIRMS"),
            },
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/critical failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/changes")
def get_hotspot_changes(
    current_days: int = Query(default=1, ge=1, le=5, description="Current snapshot days"),
    previous_days: int = Query(default=2, ge=2, le=10, description="Previous snapshot days"),
):
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

        changes = detect_changes(previous=previous_data, current=current_data)
        return changes

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/changes failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hotspots/states")
def get_hotspots_by_state(
    days: int = Query(default=1, ge=1, le=10),
    state: str = Query(default=None, description="Filter by Nigerian state name"),
):
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
                if f["properties"].get("state", "").lower() == state.lower()
            ]
            return {
                "type": "FeatureCollection",
                "features": filtered,
                "metadata": {"count": len(filtered), "state_filter": state},
            }
        else:
            state_data: dict[str, dict] = {}
            for f in features:
                s = f["properties"].get("state", "Unknown")
                if s not in state_data:
                    state_data[s] = {
                        "count": 0,
                        "high_confidence": 0,
                        "critical_threats": 0,
                        "max_score": 0,
                        "threat_tier": f["properties"].get("threat_tier", "Unknown"),
                    }
                state_data[s]["count"] += 1
                if f["properties"].get("confidence") == "H":
                    state_data[s]["high_confidence"] += 1
                if f["properties"].get("priority") == "CRITICAL":
                    state_data[s]["critical_threats"] += 1
                score = f["properties"].get("threat_score", 0)
                if score > state_data[s]["max_score"]:
                    state_data[s]["max_score"] = score

            sorted_states = dict(sorted(state_data.items(), key=lambda x: x[1]["count"], reverse=True))
            return {"states": sorted_states, "total_states_affected": len(sorted_states)}

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /hotspots/states failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hotspots/cache/clear")
def clear_cache():
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
def cache_stats():
    """View current cache statistics."""
    try:
        from ingestion.cache import firms_cache
        return firms_cache.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))