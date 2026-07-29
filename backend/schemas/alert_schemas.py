from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

# Mirrors services/platform_metrics_service.METRIC_KEYS — kept as its own closed
# vocabulary here (schemas don't import services), same pattern as
# schemas/category_schemas.py's ALLOWED_ICONS.
ALLOWED_METRIC_KEYS = ("daily_signups", "day1_retention", "day7_retention", "churn_rate", "revenue")
ALLOWED_THRESHOLD_TYPES = ("stddev_multiplier", "percent_change", "absolute")
ALLOWED_DIRECTIONS = ("above", "below", "any")
ALLOWED_CHANNELS = ("email", "slack", "push")


class ThresholdUpsertRequest(BaseModel):
    metric_key: str
    # Defaults to the acting admin — a Super Admin may pass a different admin's
    # id to assign ownership on their behalf (e.g. resolving an unassigned alert).
    owner_admin_id: Optional[str] = None
    threshold_type: str = "stddev_multiplier"
    threshold_value: float = Field(2.0, gt=0)
    direction: str = "any"
    channels: List[str] = Field(default_factory=lambda: ["email"])
    slack_webhook_url: Optional[str] = None

    @field_validator("metric_key")
    @classmethod
    def valid_metric(cls, v: str) -> str:
        if v not in ALLOWED_METRIC_KEYS:
            raise ValueError(f"Unknown metric_key. Must be one of {ALLOWED_METRIC_KEYS}")
        return v

    @field_validator("threshold_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in ALLOWED_THRESHOLD_TYPES:
            raise ValueError(f"threshold_type must be one of {ALLOWED_THRESHOLD_TYPES}")
        return v

    @field_validator("direction")
    @classmethod
    def valid_direction(cls, v: str) -> str:
        if v not in ALLOWED_DIRECTIONS:
            raise ValueError(f"direction must be one of {ALLOWED_DIRECTIONS}")
        return v

    @field_validator("channels")
    @classmethod
    def valid_channels(cls, v: List[str]) -> List[str]:
        invalid = [c for c in v if c not in ALLOWED_CHANNELS]
        if invalid:
            raise ValueError(f"Unknown channel(s): {invalid}. Must be from {ALLOWED_CHANNELS}")
        if not v:
            raise ValueError("At least one channel is required")
        return v


class AssignOwnerRequest(BaseModel):
    owner_admin_id: str = Field(min_length=1)
