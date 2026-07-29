from typing import List, Optional

from pydantic import BaseModel


class TargetPassageSchema(BaseModel):
    passage_id: str
    difficulty: str
    title: str
    text: str
    prompt_token: Optional[str] = None


class WeakPointSchema(BaseModel):
    issue: str
    detail: str


class AccentAssessmentResultSchema(BaseModel):
    assessment_id: str
    passage_id: str
    status: str
    transcript: Optional[str] = None
    pronunciation_score: Optional[float] = None
    stress_score: Optional[float] = None
    rhythm_score: Optional[float] = None
    intonation_score: Optional[float] = None
    clarity_score: Optional[float] = None
    weak_points: List[WeakPointSchema] = []
    warning: Optional[str] = None
    model_used: Optional[str] = None


class AccentProfileSchema(BaseModel):
    profile_id: str
    source_assessment_id: str
    pronunciation_score: float
    stress_score: float
    rhythm_score: float
    intonation_score: float
    clarity_score: float
    weak_points: List[WeakPointSchema]
    exercises: List[str]
    created_at: str


class RecordingRejectedSchema(BaseModel):
    """Returned (422) instead of scores when the passage reading fails a quality check."""

    status: str = "rejected"
    reason: str
    message: str


# ACC-US-12: Accent Progress Tracker Visualization
class MonthMetricSchema(BaseModel):
    month: int
    pronunciation: Optional[float] = None
    word_stress: Optional[float] = None
    intonation: Optional[float] = None
    clarity: Optional[float] = None
    is_locked: bool = False


class AccentProgressTrackerSchema(BaseModel):
    months: List[MonthMetricSchema]
    is_insufficient_data: bool = False
    regressed_metrics: List[str] = []
    cta_suggestion: Optional[str] = None
    message: Optional[str] = None


# ACC-US-13: Accent Improvement Targeted Exercises
class TargetedDrillSchema(BaseModel):
    drill_id: str
    target_phoneme: str
    issue_description: str
    sentence: str
    prompt_token: Optional[str] = None
    placement_tip: Optional[str] = None
    is_paused: bool = False


class TargetedDrillResultSchema(BaseModel):
    drill_id: str
    target_phoneme: str
    overall_score: float
    improved_vs_baseline: bool
    baseline_score: Optional[float] = None
    placement_tip: Optional[str] = None
    warning: Optional[str] = None
    model_used: Optional[str] = None


class TargetedDrillSkipResponseSchema(BaseModel):
    status: str = "skipped"
    message: str = "Consistent practice is required for measurable improvement."


