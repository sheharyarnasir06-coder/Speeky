"""
Progress Dashboard Tracking Schemas (PDG-US-10)
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class PrimaryMetricSchema(BaseModel):
    """The central, top-line metric required by PDG-US-10."""
    name: str = Field(default="Confidence Score", description="Metric display name")
    value: float = Field(default=0.0, description="Current confidence score (0-100)")
    unit: str = Field(default="pts", description="Score unit")
    is_primary: bool = Field(default=True, description="Flag identifying this as the central primary metric")
    description: str = Field(default="Your primary overall confidence indicator across all learning modules.")


class TrendPointSchema(BaseModel):
    """Single time-series point for visual graph trend lines."""
    date: str = Field(description="ISO timestamp or date string (YYYY-MM-DD)")
    confidence_score: Optional[float] = Field(None, description="Confidence score on this date (0-100)")
    fluency_score: Optional[float] = Field(None, description="Fluency score on this date (0-100)")
    vocabulary_score: Optional[float] = Field(None, description="Vocabulary score on this date (0-100)")
    pronunciation_score: Optional[float] = Field(None, description="Pronunciation score on this date (0-100)")
    practice_time_minutes: float = Field(default=0.0, description="Practice duration in minutes for this session")


class ProgressDashboardMetricsSchema(BaseModel):
    """All key summary metrics."""
    confidence_score: PrimaryMetricSchema = Field(description="Top-line central metric")
    fluency_score: Optional[float] = Field(None, description="Current overall fluency score")
    vocabulary_score: Optional[float] = Field(None, description="Current overall vocabulary score")
    pronunciation_score: Optional[float] = Field(None, description="Current overall pronunciation score")
    total_practice_time_minutes: float = Field(default=0.0, description="Cumulative practice duration in minutes")
    total_practice_time_hours: float = Field(default=0.0, description="Cumulative practice duration in hours")
    completed_sessions_count: int = Field(default=0, description="Total completed session count")
    vocabulary_growth_count: int = Field(default=0, description="New words learned / target vocab growth count")
    daily_streak_days: int = Field(default=0, description="Current practice streak in days (rolling 24-48h UTC)")


class ProgressDashboardResponseSchema(BaseModel):
    """Complete response payload for GET /api/progress-dashboard/progress."""
    user_id: str
    generated_at: str
    sync_status: str = Field(default="synced", description="Sync state: 'synced' or 'stale' (E-01 fallback)")
    is_stale: bool = Field(default=False, description="E-01: True if returning last-known-good cached snapshot")
    is_empty_state: bool = Field(default=False, description="E-02: True if user has completed zero sessions")
    empty_state_prompt: Optional[str] = Field(None, description="E-02: Motivational prompt for day-1 users")
    primary_metric: PrimaryMetricSchema = Field(description="Central top-line metric (Confidence Score)")
    summary_metrics: ProgressDashboardMetricsSchema
    trend_lines: List[TrendPointSchema] = Field(default_factory=list, description="Time-series data for visual charts")
    flagged_outliers_count: int = Field(default=0, description="E-03: Number of corrupted outlier sessions dropped from calculation")
    sync_message: Optional[str] = Field(None, description="Banner message if sync failed or empty state")
