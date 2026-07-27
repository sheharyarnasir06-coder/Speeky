"""
Accent Assessment feature area.

Holds accent assessment user stories:
- ACC-US-03 Target Accent / English Variant Selection (target_accent_selection.py)
- Shared Accent Assessment Pipeline (profile_pipeline.py)
- ACC-US-05 Accent Profile Staleness & Re-Baseline Prompt (accent_profile_staleness.py)
- ACC-US-04 Score Dispute & Manual Feedback Loop (score_dispute.py)
"""

from .accent_profile_staleness import (
    DEFAULT_DISMISS_BACKOFF_DAYS,
    DEFAULT_INACTIVITY_RESET_THRESHOLD_DAYS,
    DEFAULT_REPEATED_DISMISS_THRESHOLD,
    DEFAULT_SHORT_INTERVAL_THRESHOLD_DAYS,
    DEFAULT_STALENESS_THRESHOLD_DAYS,
    AccentProfileStalenessService,
    StalenessPromptDetails,
)
from .profile_pipeline import (
    AccentAssessmentResult,
    AccentProfile,
    AccentProfilePipelineService,
    ScoredMetric,
    calculate_overall_accent_score,
)
from .score_dispute import (
    DEFAULT_HIGH_VOLUME_DISPUTE_THRESHOLD,
    DEFAULT_MAX_DISPUTES_PER_DAY,
    DisputeReason,
    DisputeStatus,
    DisputeSubmissionResult,
    ScoreDisputeRecord,
    ScoreDisputeService,
)
from .target_accent_selection import (
    AccentChangeLogEntry,
    TargetAccentOption,
    TargetAccentRegistry,
    TargetAccentSelectionResult,
    TargetAccentSelectionService,
    UserAccentPreference,
)

__all__ = [
    # ACC-US-03
    "AccentChangeLogEntry",
    "TargetAccentOption",
    "TargetAccentRegistry",
    "TargetAccentSelectionResult",
    "TargetAccentSelectionService",
    "UserAccentPreference",
    # Shared Pipeline
    "ScoredMetric",
    "AccentAssessmentResult",
    "AccentProfile",
    "calculate_overall_accent_score",
    "AccentProfilePipelineService",
    # ACC-US-05 (Story 1)
    "DEFAULT_STALENESS_THRESHOLD_DAYS",
    "DEFAULT_DISMISS_BACKOFF_DAYS",
    "DEFAULT_REPEATED_DISMISS_THRESHOLD",
    "DEFAULT_SHORT_INTERVAL_THRESHOLD_DAYS",
    "DEFAULT_INACTIVITY_RESET_THRESHOLD_DAYS",
    "StalenessPromptDetails",
    "AccentProfileStalenessService",
    # ACC-US-04 (Story 2)
    "DEFAULT_MAX_DISPUTES_PER_DAY",
    "DEFAULT_HIGH_VOLUME_DISPUTE_THRESHOLD",
    "DisputeReason",
    "DisputeStatus",
    "ScoreDisputeRecord",
    "DisputeSubmissionResult",
    "ScoreDisputeService",
]
