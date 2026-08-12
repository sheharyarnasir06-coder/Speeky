from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.limits import MAX_SUBMISSION_CHARS


class InterviewMode(str, Enum):
    STANDARD = "standard"      
    PANEL = "panel"          
    CASE_STUDY = "case_study"  
    MULTI_ROUND = "multi_round"   


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class PersonaTone(str, Enum):
    STRICT_CORPORATE = "strict_corporate"
    FRIENDLY_STARTUP = "friendly_startup"
    FORMAL_PANEL = "formal_panel"
    NEUTRAL = "neutral"


class Panelist(BaseModel):
    """A single interviewer inside a panel/group interview."""
    name: str
    persona_tone: PersonaTone = PersonaTone.FORMAL_PANEL
    focus_area: str = Field(..., description="e.g. 'technical depth', 'culture fit'")


class StartSessionRequest(BaseModel):
    mode: InterviewMode = InterviewMode.STANDARD
    role_or_major: Optional[str] = Field(None, description="Target job role, e.g. 'Software Engineer'")
    persona_tone: PersonaTone = PersonaTone.NEUTRAL
    panelists: Optional[List[Panelist]] = None          # required if mode == PANEL
    case_type: Optional[str] = Field(None, description="'market_sizing' | 'brainteaser' | 'business_case'")
    case_difficulty: Optional[str] = Field("medium", description="'easy' | 'medium' | 'hard'")
    rounds: Optional[List[InterviewMode]] = Field(None, description="Ordered rounds for multi_round mode")

    @model_validator(mode="after")
    def panel_needs_panelists(self):
        if self.mode == InterviewMode.PANEL and not self.panelists:
            raise ValueError("panelists is required when mode is 'panel'")
        if self.mode == InterviewMode.PANEL and self.panelists and len(self.panelists) > 3:
            raise ValueError("panelists is capped at 3 — real panel interviews rarely exceed this")
        if self.mode == InterviewMode.MULTI_ROUND and self.rounds and len(self.rounds) > 4:
            raise ValueError("rounds is capped at 4 — real interview days rarely exceed this")
        return self


class SessionStartResponse(BaseModel):
    session_id: Optional[str] = None
    mode: InterviewMode
    status: SessionStatus
    current_round: Optional[str] = None
    opening_question: str
    started_at: datetime


class AnswerRequest(BaseModel):
    answer_text: str = Field(..., max_length=MAX_SUBMISSION_CHARS, description="Transcribed user answer")
    response_duration_seconds: int = Field(0, description="Length of spoken answer")
    silence_before_seconds: int = Field(0, description="Silence before user started answering")


class AIExchange(BaseModel):
    speaker: str
    question: str
    answer: Optional[str] = None
    flags: List[str] = Field(default_factory=list)


class AnswerResponse(BaseModel):
    session_id: Optional[str] = None
    next_question: Optional[str] = None
    next_speaker: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    round_complete: bool = False
    session_complete: bool = False


class PauseSessionRequest(BaseModel):
    reason: str = Field("interruption", description="'interruption' | 'manual'")


class TakeBreakRequest(BaseModel):
    pass


class RoundScorecard(BaseModel):
    round_type: InterviewMode
    scores: dict = Field(default_factory=dict, description="metric -> 0-100")
    summary: str


class SessionFeedback(BaseModel):
    session_id: Optional[str] = None
    mode: InterviewMode
    closing_message: str
    round_scorecards: List[RoundScorecard]
    #: None when nothing could be graded — no answers given, or the grader was
    #: unreachable. A session with no answers used to report 85; clients must render the
    #: `scoring_status` message instead of a number when this is None.
    overall_score: Optional[int] = None
    scoring_status: str = Field(
        "scored",
        description="'scored' | 'insufficient_evidence' | 'unavailable'",
    )
    actionable_script: str
    ended_at: datetime


class ShareReviewRequest(BaseModel):
    session_id: Optional[str] = None
    recipient_email_or_id: str
    note: Optional[str] = None
    expiry_hours: int = Field(168, description="Link expiry window, default 7 days")
    access_level: str = Field("transcript_only", description="'transcript_only' | 'full'")
    content_confirmed: bool = Field(
        False, description="E-03: user must confirm the recording/transcript before a 'full' share link"
    )


class ShareReviewResponse(BaseModel):
    share_id: str
    session_id: Optional[str] = None
    shared_with: str
    share_link: str
    access_level: str
    expires_at: datetime
    created_at: datetime


class PeerCommentRequest(BaseModel):
    comment_text: str = Field(..., max_length=MAX_SUBMISSION_CHARS)


class PeerComment(BaseModel):
    comment_id: str
    share_id: Optional[str] = None
    author_id: str
    comment_text: str = Field(..., max_length=MAX_SUBMISSION_CHARS)
    hidden: bool = False
    created_at: datetime
