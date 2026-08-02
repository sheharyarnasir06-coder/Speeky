from typing import List, Optional

from pydantic import BaseModel


class ComparisonResponse(BaseModel):
    metric_key: str
    metric_label: str
    basis: str  # WoW | MoM | YoY
    current_start: str
    current_end: str
    prior_start: str
    prior_end: str
    current_value: float
    prior_value: float
    pct_change: Optional[float]
    direction: str  # up | down | flat | new
    is_new: bool
    day_count_mismatch: bool
    outage_flagged: bool
    outage_note: Optional[str] = None


class AvailableBasesResponse(BaseModel):
    available: List[str]
    launch_date: str
    days_of_history: int


class IncidentSchema(BaseModel):
    id: str
    label: str
    start_at: str
    end_at: str


class IncidentCreateRequest(BaseModel):
    label: str
    start_at: str
    end_at: str


class IncidentListResponse(BaseModel):
    incidents: List[IncidentSchema]
