"""
Ported historical interview-simulation prototypes (US-48, US-49, US-50,
US-51, US-52).

These were originally built as standalone speeky/ modules on an
abandoned prototype branch (`Atika`, never merged into this backend) and
are restored here verbatim, only relocated + given a package init - no
logic changed. Distinct from the live, currently-wired
backend/services/interview_coach_service.py (US-40 Panel, US-42 Case
Study, US-43 Multi-Round, US-44 Mentor Review, US-45 base) - this
package is not routed through any FastAPI endpoint yet.

Every session class here expects an injected LLM/engine callable
(ask_llm, or a conversation_engine/persona_engine object) rather than
importing one directly, since the modules they were originally written
against (pipeline.py's ConversationEngine, a persona engine) were never
part of what got ported - wiring a real backend equivalent in is left to
whoever routes this.
"""

from .interview_technical import TechnicalInterviewSession
from .interview_visa import VisaInterviewSession
from .interview_scenarios import (
    LocalMarketInterviewSession,
    STARInterviewSession,
    UniversityAdmissionSession,
)

__all__ = [
    "TechnicalInterviewSession",
    "VisaInterviewSession",
    "STARInterviewSession",
    "LocalMarketInterviewSession",
    "UniversityAdmissionSession",
]
