"""
api/models/sentinel2.py
───────────────────────
Pydantic schemas for Sentinel-2 vegetation change detection endpoints.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from enum import Enum
from datetime import date


class VegetationIndexEnum(str, Enum):
    ndvi = "ndvi"
    evi  = "evi"
    savi = "savi"
    nbr  = "nbr"
    ndmi = "ndmi"


class SeverityEnum(str, Enum):
    low      = "low"
    moderate = "moderate"
    high     = "high"
    critical = "critical"


class BBoxModel(BaseModel):
    west:  float = Field(..., ge=-180, le=180, description="Western longitude")
    south: float = Field(..., ge=-90,  le=90,  description="Southern latitude")
    east:  float = Field(..., ge=-180, le=180, description="Eastern longitude")
    north: float = Field(..., ge=-90,  le=90,  description="Northern latitude")

    @validator("east")
    def east_gt_west(cls, v, values):
        if "west" in values and v <= values["west"]:
            raise ValueError("east must be greater than west")
        return v

    @validator("north")
    def north_gt_south(cls, v, values):
        if "south" in values and v <= values["south"]:
            raise ValueError("north must be greater than south")
        return v

    def to_list(self) -> List[float]:
        return [self.west, self.south, self.east, self.north]


# ── Request Schemas ───────────────────────────────────────────

class SceneSearchRequest(BaseModel):
    bbox: BBoxModel
    start_date: date
    end_date: date
    max_cloud_cover: float = Field(30.0, ge=0.0, le=100.0)
    max_results: int = Field(20, ge=1, le=100)

    class Config:
        schema_extra = {
            "example": {
                "bbox": {
                    "west": 6.0, "south": 11.5,
                    "east": 7.5, "north": 12.8,
                },
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "max_cloud_cover": 30.0,
                "max_results": 10,
            }
        }


class ChangeDetectionRequest(BaseModel):
    zone_name: Optional[str] = Field(
        None,
        description=(
            "Pre-defined monitoring zone (e.g. 'zamfara_corridor'). "
            "If provided, bbox is ignored."
        ),
    )
    bbox: Optional[BBoxModel] = Field(
        None,
        description="Custom bounding box. Required if zone_name not provided.",
    )
    date_before: Optional[date] = Field(
        None,
        description="'Before' image date. Defaults to 14 days before date_after.",
    )
    date_after: Optional[date] = Field(
        None,
        description="'After' image date. Defaults to today.",
    )
    index: VegetationIndexEnum = Field(
        VegetationIndexEnum.ndvi,
        description="Vegetation index for change detection.",
    )
    vegetation_zone: str = Field(
        "default",
        description=(
            "Vegetation zone for threshold calibration. Options: "
            "sahel, sudan_savanna, guinea_savanna, tropical_forest, "
            "mangrove, default"
        ),
    )
    max_cloud_cover: float = Field(30.0, ge=0.0, le=100.0)
    correlate_hotspots: bool = Field(
        False,
        description="Cross-reference results with FIRMS thermal hotspots.",
    )
    correlate_acled: bool = Field(
        False,
        description="Cross-reference results with ACLED conflict events.",
    )

    @validator("bbox", always=True)
    def zone_or_bbox(cls, v, values):
        if not values.get("zone_name") and v is None:
            raise ValueError("Either zone_name or bbox must be provided")
        return v

    class Config:
        schema_extra = {
            "example": {
                "zone_name": "zamfara_corridor",
                "date_before": "2024-01-01",
                "date_after": "2024-01-15",
                "index": "ndvi",
                "vegetation_zone": "sudan_savanna",
                "correlate_hotspots": True,
                "correlate_acled": False,
            }
        }


class VegetationSnapshotRequest(BaseModel):
    bbox: BBoxModel
    target_date: date = Field(..., description="Scene date (YYYY-MM-DD)")
    index: VegetationIndexEnum = VegetationIndexEnum.ndvi
    vegetation_zone: str = "default"


# ── Response Schemas ──────────────────────────────────────────

class ChangeEventResponse(BaseModel):
    event_id: str
    latitude: float
    longitude: float
    bbox: List[float]
    date_before: str
    date_after: str
    index_used: str
    mean_change: float
    max_change: float
    area_pixels: int
    area_hectares: float
    severity: SeverityEnum
    classification: str
    confidence: float
    vegetation_zone: str
    metadata: Dict = {}
    # Optional correlation fields
    nearby_hotspots: Optional[int] = None
    thermal_correlation: Optional[bool] = None
    nearest_hotspots: Optional[List[Dict]] = None
    nearby_conflicts: Optional[int] = None
    nearby_fatalities: Optional[int] = None
    conflict_correlation: Optional[bool] = None
    nearest_conflicts: Optional[List[Dict]] = None


class VegetationSnapshotResponse(BaseModel):
    date: str
    bbox: List[float]
    index_name: str
    mean: float
    median: float
    std: float
    min_val: float
    max_val: float
    valid_pixels: int
    total_pixels: int
    cloud_fraction: float
    histogram: Optional[List[int]] = None


class ChangeDetectionJobResponse(BaseModel):
    job_id: str
    zone_name: str
    bbox: List[float]
    date_before: str
    date_after: str
    vegetation_zone: str
    index: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    events_found: int
    error: Optional[str] = None
    events: List[ChangeEventResponse] = []
    snapshot_before: Optional[VegetationSnapshotResponse] = None
    snapshot_after: Optional[VegetationSnapshotResponse] = None


class SceneResponse(BaseModel):
    scene_id: str
    datetime: str
    cloud_cover: float
    bbox: List[float]
    tile_id: str
    product_type: str
    processing_level: str


class MonitoringZoneResponse(BaseModel):
    zone_id: str
    name: str
    bbox: List[float]
    risk_level: str
    description: str


class Sentinel2HealthResponse(BaseModel):
    sentinel2_configured: bool
    credentials_set: bool
    cache_dir_exists: bool
    cached_files: int
    monitoring_zones: int
    available_indices: List[str]
    vegetation_zones: List[str]