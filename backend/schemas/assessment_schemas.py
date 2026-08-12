from typing import List, Optional

from pydantic import BaseModel, Field


class AssessmentAudioTurnSchema(BaseModel):
    """One VAD utterance's worth of raw signal.

    A spoken answer usually arrives as several utterances separated by natural pauses.
    They are kept apart rather than concatenated because gluing raw word timings across
    an utterance boundary would score the gap between them as user pause time — see
    lib/session_scorer.aggregate_audio_turns, which does the combining server-side.
    """

    transcript: str = ""
    duration_seconds: float = 0.0
    word_timings: List[dict] = Field(default_factory=list)


class AssessmentAudioSchema(BaseModel):
    """Optional audio-derived signal for a spoken assessment answer (AUDIO pipeline).

    When present, the response is scored through the audio pipeline (fluency +
    pronunciation) instead of the text pipeline. Same shape as coaching's audio features
    — produced upstream by the STT/VAD agent. `text_data` still carries the transcript.
    """

    duration_seconds: float = 0.0
    word_timings: List[dict] = Field(default_factory=list)
    turns: List[AssessmentAudioTurnSchema] = Field(default_factory=list)
    speech_rate: Optional[float] = None
    pause_count: Optional[int] = None
    mean_pause_duration: Optional[float] = None
    filled_pauses: Optional[int] = None
    avg_db: Optional[float] = None
    pronunciation_score: Optional[float] = None


class SubmitResponseSchema(BaseModel):
    text_data: str = Field(min_length=1)
    clipboard_detected: bool = False
    audio_features: Optional[AssessmentAudioSchema] = None
