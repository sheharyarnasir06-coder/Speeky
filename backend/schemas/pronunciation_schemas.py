from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"


class StartSessionRequest(BaseModel):
    device_id: str = Field(..., min_length=1)


class SessionStartResponse(BaseModel):
    session_id: str
    status: SessionStatus
    phoneme: str
    phoneme_tag: str
    sentence: str
    message: Optional[str] = None  # e.g. content_gap_flagged
    started_at: datetime


class WordResultSchema(BaseModel):
    word: str
    target_index: int
    status: str  # correct | mispronounced | stress_error | skipped
    confidence: Optional[float] = None


# Alias kept so any code still typed against the pre-merge session API (which used a
# plain correct: bool) upgrades to the same 4-level status the one-shot Pronunciation
# Coach and Accent Assessment both use (ACC-US-11/ACC-US-09 calibration needs the full
# status, not just a boolean, to tell a calibrated-away regional shift from a genuine
# mispronunciation).
WordClassification = WordResultSchema


class AttemptResponse(BaseModel):
    session_id: str
    message_key: str
    message: str
    words: List[WordClassification] = Field(default_factory=list)
    transcript: str = Field("", description="What the STT pipeline actually heard, for user-visible feedback")
    next_sentence: Optional[str] = None
    next_phoneme: Optional[str] = None
    next_phoneme_tag: Optional[str] = None
    accent_profile: Optional[str] = None
    warning: Optional[str] = None
    model_used: Optional[str] = None


class RetryResponse(BaseModel):
    session_id: str
    message: str
    frustration_breakdown: bool = False
    transcript: str = Field("", description="What the STT pipeline actually heard, for user-visible feedback")


class DeviceScopedRequest(BaseModel):
    device_id: str = Field(..., min_length=1)


class InterruptResponse(BaseModel):
    session_id: str
    status: SessionStatus
    message: str


class ResumeCheckResponse(BaseModel):
    found: bool
    session_id: Optional[str] = None
    message: str
    stale: bool = False


class ResumeResponse(BaseModel):
    session_id: str
    status: SessionStatus
    phoneme: str
    phoneme_tag: str
    sentence: str
    message: str


class PhonemeAccuracy(BaseModel):
    phoneme: str
    attempts: int
    correct_words: int
    total_words: int


class SessionSummary(BaseModel):
    session_id: str
    status: SessionStatus
    attempt_count: int
    phoneme_accuracy: List[PhonemeAccuracy] = Field(default_factory=list)
    ended_at: datetime


class RecordingRejectedSchema(BaseModel):
    """Returned (422) instead of a score when the recording fails a quality check
    (liveness/playback-audio detection, ACC-US-01) — same shape the one-shot
    Pronunciation Coach and Accent Assessment both return for this exception."""

    status: str = "rejected"
    reason: str
    message: str
