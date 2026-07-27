"""
Script Practice Confidence Score — PSA-US-05 (US-157).

The learner reads a rewrite/script aloud twice: a cold baseline, then again
after practicing. Both spoken takes are scored by the SAME existing audio
confidence pipeline; the gain (after - before) is the headline number.

Re-record is fully supported: re-recording the baseline resets the final read;
each successful final read is a fresh evaluation that appends a history entry.

Voice capture is browser-side (Web Speech API) — the client posts the
recognized transcript plus the measured duration; the backend never sees raw
audio, matching how the coaching AUDIO pipeline already works.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class StartPracticeRequest(BaseModel):
    script: str = Field(..., min_length=1, description="The rewrite/script to practice aloud")
    context: Optional[str] = Field(None, description="Optional origin blurb, e.g. 'HR interview'")


class SpokenAttempt(BaseModel):
    transcript: str = Field(..., description="Browser speech-recognition transcript of the read")
    duration_seconds: float = Field(..., ge=0, description="Measured length of the spoken read")


class ReadMetrics(BaseModel):
    """Per-read delivery metrics from the existing session_scorer AUDIO pipeline."""
    confidence: float
    fluency: float
    vocabulary: float
    pronunciation: Optional[float] = None


class StartPracticeResponse(BaseModel):
    session_id: str
    status: str  # awaiting_baseline


class BaselineResponse(BaseModel):
    session_id: str
    baseline_confidence: float
    metrics: ReadMetrics
    status: str  # practicing


class AfterResponse(BaseModel):
    session_id: str
    baseline_confidence: float
    after_confidence: float
    confidence_gain: float   # after - before; can be negative
    improved: bool
    baseline_metrics: ReadMetrics
    after_metrics: ReadMetrics
    feedback: str
    history_id: str          # the history entry this evaluation created
    status: str              # completed


class PracticeSummary(BaseModel):
    session_id: str
    script: str
    context: Optional[str] = None
    status: str
    baseline_confidence: Optional[float] = None
    after_confidence: Optional[float] = None
    confidence_gain: Optional[float] = None
    created_at: str
    completed_at: Optional[str] = None


class HistoryEntry(BaseModel):
    id: str
    script: str
    context: Optional[str] = None
    baseline_confidence: float
    after_confidence: float
    confidence_gain: float
    baseline_metrics: ReadMetrics
    after_metrics: ReadMetrics
    feedback: Optional[str] = None
    created_at: str


class PaginatedHistoryResponse(BaseModel):
    entries: List[HistoryEntry]
    total: int              # total history rows for this user
    offset: int
    limit: int
    completed_count: int    # == total (every history row is a completed evaluation)
    average_gain: Optional[float] = None  # mean gain across ALL history, computed in-DB
