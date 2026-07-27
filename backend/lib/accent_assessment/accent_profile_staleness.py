"""
Accent Profile Staleness & Re-Baseline Prompt (ACC-US-05 / US-82).

Keeps the accent profile relevant by prompting re-assessment after long inactivity,
since speech patterns and skill level drift over time.

Acceptance Criteria:
- Every baseline must be timestamped; profile age must be shown to the user.
- Re-baseline must never silently overwrite historical trend data.

Exceptions:
- E-01 User Dismisses Repeatedly: reduce prompt frequency (every-login -> weekly) to avoid nagging.
- E-02 Re-Baseline Requested Too Soon (< 30 days): label it "manual refresh" rather than scheduled re-baseline.
- E-03 Inactivity Exceeds 1 Year (> 365 days): treat next assessment as a brand-new baseline (Month 1 reset).

Constants:
- Staleness threshold and dismiss-frequency backoff are named, overridable constants flagged UNCALIBRATED.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from lib.accent_assessment.profile_pipeline import (
    AccentAssessmentResult,
    AccentProfile,
    AccentProfilePipelineService,
    ScoredMetric,
    calculate_overall_accent_score,
)

logger = logging.getLogger(__name__)

# --- Overridable Constants (Flagged UNCALIBRATED per spec) ---
DEFAULT_STALENESS_THRESHOLD_DAYS: int = 60  # UNCALIBRATED: 60+ days triggers staleness
DEFAULT_DISMISS_BACKOFF_DAYS: int = 7  # UNCALIBRATED: weekly prompt backoff when dismissed repeatedly
DEFAULT_REPEATED_DISMISS_THRESHOLD: int = 3  # UNCALIBRATED: 3 dismissals trigger backoff
DEFAULT_SHORT_INTERVAL_THRESHOLD_DAYS: int = 30  # UNCALIBRATED: < 30 days labeled "manual_refresh"
DEFAULT_INACTIVITY_RESET_THRESHOLD_DAYS: int = 365  # UNCALIBRATED: > 365 days triggers Month 1 reset

PROMPT_MESSAGE_TEMPLATE = "Your accent profile is {age} days old — retake a quick baseline?"
YEAR_INACTIVITY_NOTICE = (
    "Inactivity exceeds 1 year: your next assessment will be treated as a brand-new "
    "baseline (Month 1 reset) rather than continuing an outdated trend line."
)
MANUAL_REFRESH_NOTICE = (
    "Re-baseline requested early ({age} days since last assessment). "
    "This entry is labeled as a manual refresh so it does not skew monthly comparisons."
)


@dataclass
class StalenessPromptDetails:
    """Details returned when checking staleness on user login."""

    user_id: str
    profile_age_days: int
    is_stale: bool
    should_prompt: bool
    prompt_message: Optional[str]
    prompt_frequency: str  # "every_login" or "weekly"
    suggested_rebaseline_type: str  # "scheduled_rebaseline", "manual_refresh", "brand_new_baseline"
    notice: Optional[str] = None
    last_assessment_at: Optional[datetime] = None


class AccentProfileStalenessService:
    """
    Service managing profile staleness checks, dismissal frequency backoff, and re-baselining.
    """

    def __init__(
        self,
        pipeline_service: Optional[AccentProfilePipelineService] = None,
        staleness_threshold_days: int = DEFAULT_STALENESS_THRESHOLD_DAYS,
        dismiss_backoff_days: int = DEFAULT_DISMISS_BACKOFF_DAYS,
        repeated_dismiss_threshold: int = DEFAULT_REPEATED_DISMISS_THRESHOLD,
        short_interval_threshold_days: int = DEFAULT_SHORT_INTERVAL_THRESHOLD_DAYS,
        inactivity_reset_threshold_days: int = DEFAULT_INACTIVITY_RESET_THRESHOLD_DAYS,
    ):
        self.pipeline_service = pipeline_service or AccentProfilePipelineService()
        self.staleness_threshold_days = staleness_threshold_days
        self.dismiss_backoff_days = dismiss_backoff_days
        self.repeated_dismiss_threshold = repeated_dismiss_threshold
        self.short_interval_threshold_days = short_interval_threshold_days
        self.inactivity_reset_threshold_days = inactivity_reset_threshold_days

    async def check_staleness_on_login(
        self, user_id: str, login_time: Optional[datetime] = None
    ) -> StalenessPromptDetails:
        """
        Check if user's accent profile is stale and determine if re-baseline prompt should be shown.
        Enforces E-01 (backoff frequency) and E-03 (1 year inactivity reset notice).
        """
        now = login_time or datetime.now(timezone.utc)
        profile = await self.pipeline_service.get_profile(user_id)

        if not profile or not profile.last_assessment_at:
            return StalenessPromptDetails(
                user_id=user_id,
                profile_age_days=0,
                is_stale=False,
                should_prompt=False,
                prompt_message=None,
                prompt_frequency="every_login",
                suggested_rebaseline_type="scheduled_rebaseline",
            )

        age_td = now - profile.last_assessment_at
        age_days = max(0, age_td.days)

        is_stale = age_days >= self.staleness_threshold_days

        # E-01: Reduced frequency on repeated dismissals
        prompt_frequency = "every_login"
        if profile.dismiss_count >= self.repeated_dismiss_threshold:
            prompt_frequency = "weekly"

        should_prompt = is_stale
        if is_stale and prompt_frequency == "weekly" and profile.last_dismissed_at:
            days_since_dismiss = (now - profile.last_dismissed_at).days
            if days_since_dismiss < self.dismiss_backoff_days:
                should_prompt = False

        # E-03: Inactivity exceeds 1 year
        notice = None
        if age_days >= self.inactivity_reset_threshold_days:
            suggested_type = "brand_new_baseline"
            notice = YEAR_INACTIVITY_NOTICE
        elif age_days < self.short_interval_threshold_days:
            suggested_type = "manual_refresh"
            notice = MANUAL_REFRESH_NOTICE.format(age=age_days)
        else:
            suggested_type = "scheduled_rebaseline"

        prompt_msg = PROMPT_MESSAGE_TEMPLATE.format(age=age_days) if should_prompt else None

        return StalenessPromptDetails(
            user_id=user_id,
            profile_age_days=age_days,
            is_stale=is_stale,
            should_prompt=should_prompt,
            prompt_message=prompt_msg,
            prompt_frequency=prompt_frequency,
            suggested_rebaseline_type=suggested_type,
            notice=notice,
            last_assessment_at=profile.last_assessment_at,
        )

    async def dismiss_prompt(
        self, user_id: str, dismiss_time: Optional[datetime] = None
    ) -> AccentProfile:
        """
        Record user dismissing the re-baseline prompt (E-01 backoff tracking).
        """
        now = dismiss_time or datetime.now(timezone.utc)
        profile = await self.pipeline_service.get_profile(user_id)
        if not profile:
            raise ValueError(f"No profile found for user {user_id}")

        profile.dismiss_count += 1
        profile.last_dismissed_at = now
        return await self.pipeline_service.save_profile(profile)

    async def execute_rebaseline(
        self,
        user_id: str,
        metric_scores: Dict[str, float],
        target_accent_id: Optional[str] = None,
        assessment_time: Optional[datetime] = None,
        audio_clip_id: Optional[str] = None,
        requested_type: Optional[str] = None,
    ) -> AccentAssessmentResult:
        """
        Generate a fresh baseline assessment.
        Appends to baseline history without overwriting previous data.
        """
        now = assessment_time or datetime.now(timezone.utc)
        profile = await self.pipeline_service.get_profile(user_id)

        target_accent = target_accent_id or (profile.target_accent_id if profile else "general_american")

        staleness_info = await self.check_staleness_on_login(user_id, login_time=now)
        final_type = requested_type or staleness_info.suggested_rebaseline_type

        notice = staleness_info.notice
        if final_type == "manual_refresh" and not notice:
            age = staleness_info.profile_age_days
            notice = MANUAL_REFRESH_NOTICE.format(age=age)

        metrics = {
            name: ScoredMetric(metric_name=name, score=score, audio_clip_id=audio_clip_id)
            for name, score in metric_scores.items()
        }
        overall = calculate_overall_accent_score(metrics)

        new_result = AccentAssessmentResult(
            assessment_id=f"assess_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            timestamp=now,
            metrics=metrics,
            overall_score=overall,
            target_accent_id=target_accent,
            assessment_type=final_type,
            audio_clip_id=audio_clip_id,
            notice=notice,
        )

        if not profile:
            profile = AccentProfile(
                user_id=user_id,
                target_accent_id=target_accent,
                created_at=now,
                last_assessment_at=now,
                baselines_history=[new_result],
            )
        else:
            # Mark old baselines as historical flag
            for b in profile.baselines_history:
                b.is_historical = True

            # Preserve history - append new baseline
            profile.baselines_history.append(new_result)
            profile.last_assessment_at = now
            profile.target_accent_id = target_accent
            # Reset dismissal counters upon accepting/completing rebaseline
            profile.dismiss_count = 0
            profile.last_dismissed_at = None
            if final_type == "brand_new_baseline":
                profile.is_reset_baseline = True

        await self.pipeline_service.save_profile(profile)
        return new_result
