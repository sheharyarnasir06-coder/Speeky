"""
Speeky Pronunciation Coach pipeline.

Minimal package init. The original speeky/__init__.py (pre-cleanup,
pre-restructure standalone location) eagerly imported ~15 sibling
modules (vad, asr, alignment, grammar, fluency, response, tts, pipeline,
storage, assessment, results, gating, reassessment) that no longer exist
in this repository - only pronunciation.py and confidence.py were
restored, plus the new pronunciation-coach modules below. This init only
imports what actually exists, so `import lib.pronunciation_coach`
doesn't fail on missing modules.
"""

__version__ = "0.2.0"

from .confidence import ConfidenceGrammarAnalyzer, ConfidenceScoreEngine, ScoringWeights, SessionScore
from .pronunciation import PronunciationScorer

from .pronunciation_pipeline import (
    AccentPronunciationConfigRegistry,
    ColorTier,
    PronunciationPipeline,
    PronunciationPipelineConfig,
    SentenceScoreResult,
    WordAttempt,
    WordScoreResult,
)
from .accessibility_profile import (
    AccessibilityProfile,
    AccessibilityProfileStore,
    score_with_accessibility,
    should_trigger_frustration_loop,
)
from .pronunciation_reliability import (
    AttemptStatus,
    CorruptedResponseError,
    PendingAttemptStore,
    PendingResultsBoard,
    PronunciationSubmissionManager,
    ReliabilityConfig,
    ScoringServiceError,
    SubmissionOutcome,
)
from .trouble_words import TroubleWordEntry, TroubleWordsBank, TroubleWordsConfig
from .asr_adapter import word_timings_to_attempts

__all__ = [
    "ConfidenceGrammarAnalyzer",
    "ConfidenceScoreEngine",
    "ScoringWeights",
    "SessionScore",
    "PronunciationScorer",
    "AccentPronunciationConfigRegistry",
    "ColorTier",
    "PronunciationPipeline",
    "PronunciationPipelineConfig",
    "SentenceScoreResult",
    "WordAttempt",
    "WordScoreResult",
    "AccessibilityProfile",
    "AccessibilityProfileStore",
    "score_with_accessibility",
    "should_trigger_frustration_loop",
    "AttemptStatus",
    "CorruptedResponseError",
    "PendingAttemptStore",
    "PendingResultsBoard",
    "PronunciationSubmissionManager",
    "ReliabilityConfig",
    "ScoringServiceError",
    "SubmissionOutcome",
    "TroubleWordEntry",
    "TroubleWordsBank",
    "TroubleWordsConfig",
    "word_timings_to_attempts",
]
