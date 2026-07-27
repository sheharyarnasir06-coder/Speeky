"""
Accessibility safeguard for genuine speech disorders (Story 2).

Adds an opt-in, per-user accessibility scoring profile on top of the
shared PronunciationPipeline (pronunciation_pipeline.py) - it never
re-implements scoring. When active, the profile:
  - exempts disclosed-condition disfluency (repetitions/blocks) from the
    sentence fluency_score penalty PronunciationPipeline would otherwise
    apply (E-02's stutter handling in the base pipeline),
  - leaves per-word phoneme-accuracy color tiers completely untouched,
    since those come from PronunciationPipeline's own confidence-based
    classification and must keep flagging genuine mispronunciation,
  - labels the resulting session so accessibility-profile scores are
    never silently mixed with standard-profile scores (E-04),
  - never diagnoses an undisclosed user; it may surface the opt-in
    setting once (E-01).

The AccessibilityProfile flag is injected per-call/per-user (constructor
argument, store lookup by user_id) - there is no module-level/global
toggle anywhere in this file.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence

from lib.pronunciation_coach.pronunciation_pipeline import (
    PronunciationPipeline,
    PronunciationPipelineConfig,
    SentenceScoreResult,
    WordAttempt,
)

logger = logging.getLogger(__name__)

# Session profile labels (E-04). Named, not magic strings scattered around.
STANDARD_PROFILE_LABEL = "standard"
ACCESSIBILITY_PROFILE_LABEL = "accessibility"

# Trigger-cause labels used by should_trigger_frustration_loop (E-02).
TRIGGER_CAUSE_DISFLUENCY = "disfluency"
TRIGGER_CAUSE_PHONEME_MISPRONUNCIATION = "phoneme_mispronunciation"

# Default "N consecutive fails" frustration-loop threshold. Named/overridable
# because the frustration-loop feature itself lives in another story; this
# is only the default this module assumes if the caller doesn't supply its
# own threshold. UNCALIBRATED.
DEFAULT_FRUSTRATION_LOOP_THRESHOLD = 5


@dataclass
class AccessibilityProfile:
    """A single user's accessibility scoring preference."""

    user_id: str
    opted_in: bool = False
    disclosed_condition: Optional[str] = None  # e.g. "stutter", "apraxia"
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AccessibilityProfileStore:
    """
    In-memory per-user profile store, following the same accumulate-in-
    memory pattern confidence.py's ConfidenceScoreEngine/error_history
    uses (no DB layer exists in this module set - a real deployment would
    swap this for persistent storage without changing the interface).
    """

    def __init__(self):
        self._profiles: Dict[str, AccessibilityProfile] = {}
        self._nudge_shown: Dict[str, bool] = {}

    def get(self, user_id: str) -> AccessibilityProfile:
        return self._profiles.get(user_id, AccessibilityProfile(user_id=user_id, opted_in=False))

    def set_opt_in(self, user_id: str, opted_in: bool, disclosed_condition: Optional[str] = None) -> AccessibilityProfile:
        """
        Opt in/out. Available any time from settings (acceptance
        criteria) - this is just a plain setter, callable from onboarding
        or a settings screen equally.
        """
        profile = AccessibilityProfile(
            user_id=user_id,
            opted_in=opted_in,
            disclosed_condition=disclosed_condition if opted_in else None,
        )
        self._profiles[user_id] = profile
        logger.info("Accessibility profile for %s set: opted_in=%s", user_id, opted_in)
        return profile

    def maybe_surface_nudge(self, user_id: str, undisclosed_pattern_detected: bool) -> Optional[str]:
        """
        E-01: Undisclosed Pattern Detected.

        Never diagnoses or labels the user's pattern. If a consistent
        disfluency pattern is observed for a user who has NOT opted in,
        may gently surface the optional setting - but only once ever,
        even if the pattern keeps recurring after being declined.
        """
        profile = self.get(user_id)
        if profile.opted_in:
            return None
        if not undisclosed_pattern_detected:
            return None
        if self._nudge_shown.get(user_id):
            return None

        self._nudge_shown[user_id] = True
        return (
            "Tip: if speech practice feels more comfortable at your own pace, "
            "you can turn on an accessibility-aware scoring mode any time in Settings."
        )


def should_trigger_frustration_loop(
    profile: AccessibilityProfile,
    trigger_cause: str,
    consecutive_failures: int,
    threshold: int = DEFAULT_FRUSTRATION_LOOP_THRESHOLD,
) -> bool:
    """
    E-02: Conflict with the standard "frustration-loop" 5-fail intervention.

    When the accessibility profile is active, the frustration-loop
    threshold is disabled for failures caused by the disclosed disfluency
    pattern, but stays active for genuine phoneme mispronunciation.
    """
    if profile.opted_in and trigger_cause == TRIGGER_CAUSE_DISFLUENCY:
        return False
    return consecutive_failures >= threshold


def score_with_accessibility(
    pipeline: PronunciationPipeline,
    target_sentence: str,
    attempts: Sequence[Optional[WordAttempt]],
    profile: AccessibilityProfile,
    accent_calibration: bool = False,
    config_override: Optional[PronunciationPipelineConfig] = None,
) -> SentenceScoreResult:
    """
    Score a sentence through the shared pipeline, applying the
    accessibility exemption when `profile.opted_in`.

    E-03: for a user with no disclosed condition (profile.opted_in is
    False), this is a pure pass-through to PronunciationPipeline - casual
    nervous disfluency gets the standard, unmodified fluency penalty.

    `config_override` (added for the accent_assessment wiring) lets a
    caller pass an accent-resolved PronunciationPipelineConfig (e.g. from
    pipeline.resolve_config_for_user()) through to score_sentence() without
    mutating pipeline.config - same optional, backward-compatible
    parameter score_sentence() itself already exposes. Existing callers
    that never pass it get byte-identical behavior to before this param
    existed.
    """
    exempt_indices = set()
    if profile.opted_in:
        exempt_indices = {
            i
            for i, a in enumerate(attempts)
            if a is not None and a.repetitions >= pipeline.config.stutter_repetition_threshold
        }

    result = pipeline.score_sentence(
        target_sentence=target_sentence,
        attempts=attempts,
        accent_calibration=accent_calibration,
        accessibility_exempt_indices=exempt_indices,
        config_override=config_override,
    )

    result.scoring_profile = ACCESSIBILITY_PROFILE_LABEL if profile.opted_in else STANDARD_PROFILE_LABEL

    if profile.opted_in:
        for word in result.words:
            if word.index in exempt_indices:
                # Feedback language must never imply the disclosed trait is
                # an error (acceptance criteria).
                word.note = "natural repetition (accessibility profile active) - not scored as an error"

    return result
