"""Public Speaking Coach schemas for PSC-US-01, PSC-US-03, PSC-US-04, PSC-US-05, PSC-US-06, PSC-US-07, PSC-US-11, PSC-US-12, PSC-US-14"""

from pydantic import BaseModel, Field

from schemas.limits import MAX_SHORT_TEXT_CHARS, MAX_SUBMISSION_CHARS
from schemas.video_features_schema import VideoFeaturesSchema
from typing import Optional, List, Dict, Literal


class StartPublicSpeakingSchema(BaseModel):
    """Request to start a public speaking session"""
    speech_type: Literal["business_pitch", "casual_event", "motivational", "classroom", "ted_talk"]
    # "audio_video" is audio PLUS an opted-in camera — there is no video-only mode, because
    # physical delivery is only ever scored alongside a spoken turn. Stored as a plain String
    # column, so widening this Literal needs no migration.
    input_mode: Literal["audio", "text", "audio_video"] = Field(
        default="audio", description="Audio, text, or audio with camera-based delivery analysis"
    )
    topic: Optional[str] = Field(None, max_length=MAX_SHORT_TEXT_CHARS, description="Optional topic/prompt for the speech")


class PublicSpeakingTurnSchema(BaseModel):
    """Submit a speech turn (audio or text).

    Voice comes through the shared WebSocket voice pipeline: the backend transcribes 
    in realtime and the client sends the transcript as text_content plus duration_seconds.
    routes it through the audio scoring path (real WPM; tone/clarity are proxies since
    raw audio never reaches the backend). audio_data is the legacy base64-upload path,
    still accepted.
    """
    audio_data: Optional[str] = Field(None, description="Base64 encoded audio file (legacy path)")
    text_content: Optional[str] = Field(None, max_length=MAX_SUBMISSION_CHARS, description="Transcript (voice) or typed text")
    duration_seconds: Optional[float] = Field(None, description="Spoken duration, when voice")
    audio_features: Optional[Dict] = Field(
        None,
        description="Full-mode features from voice_ws.py: word_timings, avg_db, "
        "pitch_range_semitones, duration_seconds. Enables real tone/clarity scoring.",
    )
    # Typed, unlike audio_features above — a malformed video payload should 422 at the boundary
    # rather than reach video_scorer as an arbitrary dict. See schemas/video_features_schema.py
    # for why every metric inside is nullable.
    video_features: Optional[VideoFeaturesSchema] = Field(
        None,
        description="Aggregated physical-delivery metrics computed by MediaPipe in the browser "
        "(frontend/lib/vision/). No video, frames, or per-frame landmarks are ever uploaded.",
    )
    is_final: bool = Field(default=False, description="Whether this is the final submission")


class QAResponseSchema(BaseModel):
    """Response to AI-generated Q&A question"""
    audio_data: Optional[str] = Field(None, description="Base64 encoded audio response (legacy)")
    text_content: Optional[str] = Field(None, max_length=MAX_SUBMISSION_CHARS, description="Transcript (voice) or typed text")
    duration_seconds: Optional[float] = Field(None, description="Spoken duration, when voice")


class PublicSpeakingScorecard(BaseModel):
    """Comprehensive scorecard for public speaking analysis"""
    speech_type: str
    input_mode: str
    
    # Overall scores. On a scenario with Q&A (business_pitch, classroom, ted_talk) both of these
    # are rewritten once the Q&A is answered — 70% speech, 30% Q&A — so they are the session's
    # total, not the speech's. speech_only_score keeps the delivery half readable.
    overall_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    speech_only_score: Optional[float] = Field(
        None, ge=0, le=100,
        description="overall_score before the Q&A was folded in. Equal to overall_score until "
        "the Q&A is answered, and absent on rows scored before scoring_version 3.",
    )
    speech_only_confidence: Optional[float] = Field(
        None, ge=0, le=100,
        description="confidence before the Q&A was folded in. Written only once a blend has "
        "happened; it is the anchor that keeps a repeated blend idempotent.",
    )
    
    # Detailed metrics
    pacing: float = Field(ge=0, le=100, description="Speaking pace score (WPM analysis)")
    tone_variation: float = Field(ge=0, le=100, description="Vocal variety and energy")
    voice_clarity: float = Field(ge=0, le=100, description="Projection and diction")
    structure: float = Field(ge=0, le=100, description="Speech structure and organization")
    audience_engagement: float = Field(ge=0, le=100, description="Audience connection")
    
    # Specific metrics
    words_per_minute: Optional[float] = Field(None, description="Calculated WPM")
    filler_word_count: int = Field(default=0, description="Total filler words detected")
    filler_words: List[Dict] = Field(default_factory=list, description="List of filler words with timestamps")
    
    # Narrative analysis (for TED-style, motivational)
    narrative_arc: Optional[float] = Field(None, ge=0, le=100, description="Storytelling quality")
    emotional_connection: Optional[float] = Field(None, ge=0, le=100, description="Emotional resonance")
    
    # Business pitch specific
    pitch_structure: Optional[float] = Field(None, ge=0, le=100, description="Hook-Problem-Solution-Ask structure")
    persuasiveness: Optional[float] = Field(None, ge=0, le=100, description="Persuasive impact")
    
    # Q&A specific
    qa_handling: Optional[Dict] = Field(None, description="Q&A performance if applicable")
    
    # Feedback
    flags: List[Dict] = Field(default_factory=list, description="Issues and suggestions")
    highlights: List[Dict] = Field(default_factory=list, description="Positive moments")
    summary: str = Field(default="", description="Overall feedback summary")
    actionable_tips: List[str] = Field(default_factory=list, description="Specific improvement suggestions")
    
    # Audio delivery metrics
    delivery: Optional[Dict] = Field(None, description="Audio quality metrics")

    # Scenario-conditioned emotional register — how well the delivery matched what this kind of
    # speech asks for. Never an emotion label; see lib/register_scorer.py.
    emotional_register: Optional[float] = Field(
        None, ge=0, le=100, description="Match between delivery and the scenario's expected register"
    )
    register_detail: Optional[Dict] = Field(
        None,
        description="register_scorer.ScoredRegister.to_dict(): per-channel voice/face/word "
        "sub-scores, confidence_weight, and the expected bands. Channels are null when their "
        "source was absent (no camera, text mode, transcript too short). Named _detail because "
        "a bare 'register' field shadows a BaseModel attribute inherited from ABCMeta.",
    )
    scoring_version: int = Field(
        1,
        description="2 once the voice register channel began modulating tone_variation and "
        "audience_engagement. 3 once overall_score/confidence became a 70/30 blend of the speech "
        "and the Q&A on qa_enabled scenarios. Rows are not directly comparable across versions "
        "on those axes.",
    )

    # Physical delivery (camera sessions only). Deliberately NOT folded into overall_score —
    # see _generate_scorecard for why. None whenever the camera was off.
    visual_presence: Optional[float] = Field(
        None, ge=0, le=100, description="Composite physical-presence score, camera sessions only"
    )
    video_timeline: Optional[Dict] = Field(
        None,
        description="Per-second channels echoed back for the results sparklines. Stored, not scored.",
    )
    video: Optional[Dict] = Field(
        None,
        description="video_scorer.ScoredVideo.to_dict(): eye_contact/posture/gestures/expression/"
        "stillness sub-scores, confidence_weight, rejection reason, and detail. Sub-scores are "
        "null when that family was unmeasurable.",
    )


class PublicSpeakingSession(BaseModel):
    """Public speaking session model"""
    session_id: str
    user_id: str
    speech_type: str
    input_mode: str
    status: Literal["in_progress", "completed", "qa_phase"]
    created_at: str
    completed_at: Optional[str] = None
    scorecard: Optional[PublicSpeakingScorecard] = None
    transcript: Optional[str] = None
    ai_question: Optional[str] = Field(None, description="AI-generated Q&A question")
    user_qa_response: Optional[str] = Field(None, description="User's Q&A response")
