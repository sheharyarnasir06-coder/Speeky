from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.limits import MAX_SHORT_TEXT_CHARS, MAX_SUBMISSION_CHARS


class AudioFeaturesSchema(BaseModel):
    """Audio-derived signal from the Livekit + SileroVAD + faster-whisper agent.

    The backend never receives raw audio — only these extracted features (see
    speech-to-text/agent.py). Either provide word_timings and let the scorer derive
    speech_rate/pause_count, or supply the aggregates directly.
    """

    transcript: str = ""
    duration_seconds: float = 0.0
    word_timings: List[dict] = Field(default_factory=list)  # [{"word","start","end"}]
    speech_rate: Optional[float] = None
    pause_count: Optional[int] = None
    mean_pause_duration: Optional[float] = None
    filled_pauses: Optional[int] = None
    avg_db: Optional[float] = None
    pronunciation_score: Optional[float] = None


class StartCoachingSchema(BaseModel):
    scenario: str  # one of WORKPLACE_SCENARIOS keys
    input_mode: Optional[str] = None  # only honored for general_workplace
    prompt: Optional[str] = None      # custom brief; defaults to a scenario example


class SubmitCoachingSchema(BaseModel):
    submission: Optional[str] = Field(None, max_length=MAX_SUBMISSION_CHARS)  # typed text OR final transcript
    subject: Optional[str] = Field(None, max_length=MAX_SHORT_TEXT_CHARS)     # email subject line
    audio_features: Optional[AudioFeaturesSchema] = None


class RoleplayTurnSchema(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_SUBMISSION_CHARS)
