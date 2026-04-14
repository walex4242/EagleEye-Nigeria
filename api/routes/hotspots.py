from fastapi import APIRouter, HTTPException, Query
from ingestion.firms import fetch_hotspots

router = APIRouter()


@router.get("/hotspots")
def get_hotspots(
    days: int = Query(default=1, ge=1, le=10, description="Number of past days to fetch"),
    country: str = Query(default="NGA", description="Country code (ISO 3166-1 alpha-3)")
):
    """
    Fetch thermal hotspots from NASA FIRMS.
    Returns a GeoJSON FeatureCollection of fire/heat detections.
    """
    try:
        data = fetch_hotspots(days=days, country=country)
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch hotspot data: {str(e)}")


@router.get("/hotspots/summary")
def get_hotspots_summary(
    days: int = Query(default=1, ge=1, le=10)
):
    """
    Returns a count summary of hotspots by region.
    """
    try:
        data = fetch_hotspots(days=days, country="NGA")
        features = data.get("features", [])

        summary = {
            "total": len(features),
            "high_confidence": sum(
                1 for f in features
                if f["properties"].get("confidence", "").upper() == "H"
            ),
            "medium_confidence": sum(
                1 for f in features
                if f["properties"].get("confidence", "").upper() == "N"
            ),
            "low_confidence": sum(
                1 for f in features
                if f["properties"].get("confidence", "").upper() == "L"
            ),
            "days_queried": days
        }
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))