"""
acled.py
─────────
API routes for ACLED conflict data and hotspot correlation.
"""

from fastapi import APIRouter, HTTPException, Query
import traceback

router = APIRouter()


@router.get("/conflicts")
def get_conflicts(
    days: int = Query(default=30, ge=1, le=365, description="Number of past days"),
    event_type: str = Query(default=None, description="Filter: Battles, Violence against civilians, etc."),
    limit: int = Query(default=5000, ge=1, le=5000),
):
    """
    Fetch conflict events from ACLED for Nigeria.
    Returns a GeoJSON FeatureCollection.
    """
    try:
        from ingestion.acled import fetch_acled_events

        event_types = None
        if event_type:
            event_types = [t.strip() for t in event_type.split(",")]

        data = fetch_acled_events(days=days, event_types=event_types, limit=limit)
        return data

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /conflicts failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conflicts/summary")
def get_conflicts_summary(
    days: int = Query(default=30, ge=1, le=365),
):
    """
    Returns a summary of recent conflict events in Nigeria.
    """
    try:
        from ingestion.acled import fetch_acled_events

        data = fetch_acled_events(days=days)
        features = data.get("features", [])

        # Event type breakdown
        type_counts: dict[str, int] = {}
        for f in features:
            et = f["properties"].get("event_type", "Unknown")
            type_counts[et] = type_counts.get(et, 0) + 1

        # State breakdown
        state_counts: dict[str, dict] = {}
        for f in features:
            state = f["properties"].get("admin1", "Unknown")
            if state not in state_counts:
                state_counts[state] = {"events": 0, "fatalities": 0}
            state_counts[state]["events"] += 1
            state_counts[state]["fatalities"] += f["properties"].get("fatalities", 0)

        top_states = dict(sorted(state_counts.items(), key=lambda x: x[1]["fatalities"], reverse=True)[:15])

        total_fatalities = sum(f["properties"].get("fatalities", 0) for f in features)

        # Actor breakdown
        actor_counts: dict[str, int] = {}
        for f in features:
            a1 = f["properties"].get("actor1", "")
            if a1:
                actor_counts[a1] = actor_counts.get(a1, 0) + 1
        top_actors = dict(sorted(actor_counts.items(), key=lambda x: x[1], reverse=True)[:10])

        return {
            "total_events": len(features),
            "total_fatalities": total_fatalities,
            "days_queried": days,
            "event_types": type_counts,
            "top_states": top_states,
            "top_actors": top_actors,
            "source": data.get("metadata", {}).get("source", "ACLED"),
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /conflicts/summary failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlate")
def correlate_hotspots_with_conflicts(
    hotspot_days: int = Query(default=1, ge=1, le=10),
    conflict_days: int = Query(default=30, ge=1, le=365),
    radius_km: float = Query(default=25.0, ge=1, le=100, description="Correlation radius in km"),
):
    """
    Correlate FIRMS thermal hotspots with ACLED conflict events.
    Returns enriched hotspot data showing nearby conflict activity.
    """
    try:
        from ingestion.firms import fetch_hotspots
        from ingestion.acled import fetch_acled_events, correlate_with_hotspots
        from analysis.anomaly_score import score_hotspots
        from analysis.region_classifier import enrich_with_regions

        # Fetch both datasets
        hotspots = fetch_hotspots(days=hotspot_days, country="NGA")
        hotspots = enrich_with_regions(hotspots)
        hotspots = score_hotspots(hotspots)

        acled = fetch_acled_events(days=conflict_days)

        # Correlate
        correlated = correlate_with_hotspots(hotspots, acled, radius_km=radius_km)

        return correlated

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] /correlate failed:\n{tb}")
        raise HTTPException(status_code=500, detail=str(e))