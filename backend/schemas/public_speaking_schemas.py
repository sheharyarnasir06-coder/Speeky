"""Public Speaking Coach schemas for PSC-US-01, PSC-US-03, PSC-US-04, PSC-US-05, PSC-US-06, PSC-US-07, PSC-US-11, PSC-US-12, PSC-US-14"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal


class StartPublicSpeakingSchema(BaseModel):
    """Request to start a public speaking session"""
    speech_type: Literal["business_pitch", "casual_event", "motivational", "classroom", "ted_talk"]
    input_mode: Literal["audio", "text"] = Field(default="audio", description="Audio or text input")
    topic: Optional[str] = Field(None, description="Optional topic/prompt for the speech")


class PublicSpeakingTurnSchema(BaseModel):
    """Submit a speech turn (audio or text).

    Voice now comes through the shared LiveKit voice pipeline (same as Conversation /
    Baseline): the voice_agent worker transcribes and the client sends the transcript as
    text_content plus duration_seconds. duration_seconds routes it through the audio
    scoring path (real WPM; tone/clarity are proxies since raw audio never reaches the
    backend). audio_data is the legacy base64-upload path, still accepted.
    """
    audio_data: Optional[str] = Field(None, description="Base64 encoded audio file (legacy path)")
    text_content: Optional[str] = Field(None, description="Transcript (voice) or typed text")
    duration_seconds: Optional[float] = Field(None, description="Spoken duration, when voice")
    audio_features: Optional[Dict] = Field(
        None,
        description="Full-mode LiveKit features from the voice_agent: word_timings, "
        "avg_db, pitch_range_semitones, duration_seconds. Enables real tone/clarity scoring.",
    )
    is_final: bool = Field(default=False, description="Whether this is the final submission")


class QAResponseSchema(BaseModel):
    """Response to AI-generated Q&A question"""
    audio_data: Optional[str] = Field(None, description="Base64 encoded audio response (legacy)")
    text_content: Optional[str] = Field(None, description="Transcript (voice) or typed text")
    duration_seconds: Optional[float] = Field(None, description="Spoken duration, when voice")


class PublicSpeakingScorecard(BaseModel):
    """Comprehensive scorecard for public speaking analysis"""
    speech_type: str
    input_mode: str
    
    # Overall scores
    overall_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    
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
