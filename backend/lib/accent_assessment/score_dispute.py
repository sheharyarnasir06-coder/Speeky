"""
Score Dispute & Manual Feedback Loop (ACC-US-04 / US-83).

Allows a user who believes an AI accent score was inaccurate to flag it for review,
building trust and generating labeled data for model improvement.

Acceptance Criteria:
- Dispute action must be available on EVERY scored metric, not just the overall score.
- System must NOT auto-correct the score without either an automated re-scoring pass or human/model review.

Exceptions:
- E-01 High Volume of Disputes on Same Drill: auto-flag the drill for content-team review of possible scoring-model bias.
- E-02 Repeated Frivolous Disputes by Single User: rate-limit disputes per user per day, display remaining allowance.
- E-03 Dispute on Deleted Audio (auto-purged per retention policy): inform user raw audio no longer available, offer fresh re-assessment.

Constants:
- Dispute rate-limit count and high-volume threshold are named, overridable constants flagged UNCALIBRATED.
"""

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from lib.accent_assessment.profile_pipeline import AccentAssessmentResult

logger = logging.getLogger(__name__)

NAMESPACE = "accent_score_disputes"

# --- Overridable Constants (Flagged UNCALIBRATED per spec) ---
DEFAULT_MAX_DISPUTES_PER_DAY: int = 3  # UNCALIBRATED: max disputes allowed per user per day
DEFAULT_HIGH_VOLUME_DISPUTE_THRESHOLD: int = 5  # UNCALIBRATED: 5+ disputes on same drill auto-flags for content team


class DisputeReason(str, Enum):
    BACKGROUND_NOISE = "background_noise"
    MISHEARD_WORD = "misheard_word"
    UNFAIR_PENALTY = "unfair_penalty"
    OTHER = "other"


class DisputeStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    UNDER_REVIEW = "under_review"
    RESOLVED_SCORE_ADJUSTED = "resolved_score_adjusted"
    RESOLVED_SCORE_KEPT = "resolved_score_kept"
    REJECTED = "rejected"


@dataclass
class ScoreDisputeRecord:
    """Record of a score dispute submitted by a user for a specific metric."""

    dispute_id: str
    user_id: str
    assessment_id: str
    metric_name: str  # Can be "pronunciation", "word_stress", "intonation", "clarity", "overall"
    original_score: float
    reason: str
    user_comment: Optional[str] = None
    audio_clip_id: Optional[str] = None
    audio_available: bool = True
    status: str = DisputeStatus.PENDING_REVIEW.value
    created_at: datetime = None  # type: ignore
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    revised_score: Optional[float] = None
    auto_flagged_for_content_team: bool = False
    notification: Optional[str] = None


@dataclass
class DisputeSubmissionResult:
    """Response payload for dispute submission."""

    success: bool
    dispute: Optional[ScoreDisputeRecord] = None
    remaining_allowance: int = 0
    max_daily_allowance: int = DEFAULT_MAX_DISPUTES_PER_DAY
    error_message: Optional[str] = None
    offer_reassessment: bool = False
    auto_flagged_for_content_team: bool = False
    notice: Optional[str] = None


def _dispute_to_dict(record: ScoreDisputeRecord) -> Dict[str, Any]:
    return asdict(record)


def _dispute_from_dict(d: Dict[str, Any]) -> ScoreDisputeRecord:
    return ScoreDisputeRecord(
        dispute_id=d["dispute_id"],
        user_id=d["user_id"],
        assessment_id=d["assessment_id"],
        metric_name=d["metric_name"],
        original_score=float(d["original_score"]),
        reason=d["reason"],
        user_comment=d.get("user_comment"),
        audio_clip_id=d.get("audio_clip_id"),
        audio_available=d.get("audio_available", True),
        status=d.get("status", DisputeStatus.PENDING_REVIEW.value),
        created_at=d["created_at"],
        reviewed_at=d.get("reviewed_at"),
        review_notes=d.get("review_notes"),
        revised_score=float(d["revised_score"]) if d.get("revised_score") is not None else None,
        auto_flagged_for_content_team=d.get("auto_flagged_for_content_team", False),
        notification=d.get("notification"),
    )


class ScoreDisputeService:
    """
    Manages score disputes, daily rate-limiting, audio availability checks, and review resolution.
    Reuses lib/kv_store.py for persistence.
    """

    def __init__(
        self,
        max_disputes_per_day: int = DEFAULT_MAX_DISPUTES_PER_DAY,
        high_volume_threshold: int = DEFAULT_HIGH_VOLUME_DISPUTE_THRESHOLD,
        store: Optional[Any] = None,
    ):
        self.max_disputes_per_day = max_disputes_per_day
        self.high_volume_threshold = high_volume_threshold
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            from lib import kv_store

            self._store = kv_store.store
        return self._store

    async def _list_all_disputes(self) -> List[ScoreDisputeRecord]:
        raw_list = await self.store.list_values(NAMESPACE)
        return [_dispute_from_dict(raw) for raw in raw_list]

    async def get_dispute(self, dispute_id: str) -> Optional[ScoreDisputeRecord]:
        raw = await self.store.get(NAMESPACE, dispute_id)
        return _dispute_from_dict(raw) if raw else None

    async def get_user_disputes(self, user_id: str) -> List[ScoreDisputeRecord]:
        all_disputes = await self._list_all_disputes()
        return [d for d in all_disputes if d.user_id == user_id]

    async def get_assessment_disputes(self, assessment_id: str) -> List[ScoreDisputeRecord]:
        all_disputes = await self._list_all_disputes()
        return [d for d in all_disputes if d.assessment_id == assessment_id]

    async def get_remaining_daily_disputes(
        self, user_id: str, current_time: Optional[datetime] = None
    ) -> int:
        """E-02: Calculate remaining dispute allowance for user today."""
        now = current_time or datetime.now(timezone.utc)
        user_disputes = await self.get_user_disputes(user_id)
        today_disputes = [
            d for d in user_disputes if d.created_at.date() == now.date()
        ]
        return max(0, self.max_disputes_per_day - len(today_disputes))

    async def submit_dispute(
        self,
        user_id: str,
        assessment: AccentAssessmentResult,
        metric_name: str,
        reason: str,
        user_comment: Optional[str] = None,
        current_time: Optional[datetime] = None,
    ) -> DisputeSubmissionResult:
        """
        Submit a score dispute for any metric on an assessment.
        Checks E-03 (audio deleted), E-02 (rate limiting), and E-01 (high dispute volume).
        Ensures score is NOT auto-corrected without review.
        """
        now = current_time or datetime.now(timezone.utc)

        # Validate metric is available on assessment (available on EVERY scored metric!)
        metric = assessment.get_metric(metric_name)
        if not metric:
            return DisputeSubmissionResult(
                success=False,
                error_message=f"Metric '{metric_name}' is not a scored metric on assessment {assessment.assessment_id}.",
                remaining_allowance=await self.get_remaining_daily_disputes(user_id, current_time=now),
                max_daily_allowance=self.max_disputes_per_day,
            )

        # E-03: Dispute on deleted audio
        if not assessment.is_audio_available:
            remaining = await self.get_remaining_daily_disputes(user_id, current_time=now)
            return DisputeSubmissionResult(
                success=False,
                error_message=(
                    "Raw audio clip for this assessment is no longer available (auto-purged per retention policy)."
                ),
                offer_reassessment=True,
                remaining_allowance=remaining,
                max_daily_allowance=self.max_disputes_per_day,
            )

        # E-02: Rate limit check per user per day
        remaining_allowance = await self.get_remaining_daily_disputes(user_id, current_time=now)
        if remaining_allowance <= 0:
            return DisputeSubmissionResult(
                success=False,
                error_message=(
                    f"Daily dispute limit reached ({self.max_disputes_per_day} per day). "
                    "Remaining allowance: 0. Please try again tomorrow."
                ),
                remaining_allowance=0,
                max_daily_allowance=self.max_disputes_per_day,
            )

        # E-01: Check high volume of disputes on same drill/assessment
        existing_assessment_disputes = await self.get_assessment_disputes(assessment.assessment_id)
        total_disputes_count = len(existing_assessment_disputes) + 1
        auto_flagged = total_disputes_count >= self.high_volume_threshold

        notice = None
        if auto_flagged:
            notice = (
                f"High volume of disputes detected for assessment '{assessment.assessment_id}' "
                f"({total_disputes_count} disputes). Auto-flagged for content team review of possible scoring-model bias."
            )

        dispute_id = f"disp_{uuid.uuid4().hex[:12]}"

        # Acceptance Criteria: System MUST NOT auto-correct score without review!
        # Status remains PENDING_REVIEW and score remains original.
        record = ScoreDisputeRecord(
            dispute_id=dispute_id,
            user_id=user_id,
            assessment_id=assessment.assessment_id,
            metric_name=metric_name,
            original_score=metric.score,
            reason=reason,
            user_comment=user_comment,
            audio_clip_id=metric.audio_clip_id or assessment.audio_clip_id,
            audio_available=assessment.is_audio_available,
            status=DisputeStatus.PENDING_REVIEW.value,
            created_at=now,
            auto_flagged_for_content_team=auto_flagged,
        )

        await self.store.create(NAMESPACE, dispute_id, _dispute_to_dict(record))

        # Also flag existing stored disputes for this assessment if threshold was just crossed
        if auto_flagged and len(existing_assessment_disputes) > 0:
            for prev_disp in existing_assessment_disputes:
                if not prev_disp.auto_flagged_for_content_team:
                    prev_disp.auto_flagged_for_content_team = True
                    await self.store.update(NAMESPACE, prev_disp.dispute_id, _dispute_to_dict(prev_disp))

        new_remaining = remaining_allowance - 1

        return DisputeSubmissionResult(
            success=True,
            dispute=record,
            remaining_allowance=new_remaining,
            max_daily_allowance=self.max_disputes_per_day,
            auto_flagged_for_content_team=auto_flagged,
            notice=notice,
        )

    async def resolve_dispute(
        self,
        dispute_id: str,
        new_status: str,
        revised_score: Optional[float] = None,
        review_notes: Optional[str] = None,
        reviewed_time: Optional[datetime] = None,
    ) -> ScoreDisputeRecord:
        """
        Complete human or model review of a dispute.
        Scores are ONLY modified here after automated re-scoring pass or human review.
        Generates a user notification.
        """
        now = reviewed_time or datetime.now(timezone.utc)
        record = await self.get_dispute(dispute_id)
        if not record:
            raise ValueError(f"Dispute {dispute_id} not found")

        record.status = new_status
        record.reviewed_at = now
        record.review_notes = review_notes
        if revised_score is not None:
            record.revised_score = revised_score

        # Generate notification for user
        if new_status == DisputeStatus.RESOLVED_SCORE_ADJUSTED.value:
            record.notification = (
                f"Your dispute for metric '{record.metric_name}' has been reviewed and approved. "
                f"Revised score: {revised_score} (was {record.original_score})."
            )
        elif new_status == DisputeStatus.RESOLVED_SCORE_KEPT.value:
            record.notification = (
                f"Your dispute for metric '{record.metric_name}' has been reviewed. "
                f"The original score of {record.original_score} was confirmed."
            )
        else:
            record.notification = f"Your score dispute has been updated to status: {new_status}."

        await self.store.update(NAMESPACE, dispute_id, _dispute_to_dict(record))
        return record
