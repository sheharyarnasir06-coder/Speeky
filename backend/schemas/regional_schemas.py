from typing import List, Optional

from pydantic import BaseModel


class RegionRollupSchema(BaseModel):
    region_code: str
    region_label: str
    value: float
    sample_size: int
    is_low_volume: bool
    is_unknown: bool
    is_other_bucket: bool
    is_spoofing_flagged: bool
    spoofing_note: Optional[str] = None


class RegionalSegmentationResponse(BaseModel):
    metric_key: str
    metric_label: str
    date_from: str
    date_to: str
    min_sample_size: int
    regions: List[RegionRollupSchema]
    computed_at: Optional[str] = None
    stale: bool = False  # True if no rollup has been precomputed yet


class RegionFeatureAdoptionRow(BaseModel):
    feature_label: str
    started: int
    completed: int
    completion_rate: float


class RegionDrilldownResponse(BaseModel):
    region_code: str
    region_label: str
    is_low_volume: bool
    sample_size: int
    features: List[RegionFeatureAdoptionRow]
    insufficient_data: bool = False
