"""
Tests for ACC-US-04 / US-83 (lib/accent_assessment/score_dispute.py).
"""

from datetime import datetime, timezone

import pytest

from lib.accent_assessment.profile_pipeline import AccentAssessmentResult, ScoredMetric
from lib.accent_assessment.score_dispute import (
    DEFAULT_HIGH_VOLUME_DISPUTE_THRESHOLD,
    DEFAULT_MAX_DISPUTES_PER_DAY,
    DisputeReason,
    DisputeStatus,
    ScoreDisputeService,
)
from lib.kv_store import InMemoryKvStore


def make_assessment_result(
    user_id: str = "user_1",
    assessment_id: str = "assess_1",
    is_audio_available: bool = True,
) -> AccentAssessmentResult:
    metrics = {
        "pronunciation": ScoredMetric("pronunciation", 70.0, audio_clip_id="audio_p"),
        "word_stress": ScoredMetric("word_stress", 65.0, audio_clip_id="audio_s"),
        "intonation": ScoredMetric("intonation", 80.0, audio_clip_id="audio_i"),
        "clarity": ScoredMetric("clarity", 75.0, audio_clip_id="audio_c"),
    }
    return AccentAssessmentResult(
        assessment_id=assessment_id,
        user_id=user_id,
        timestamp=datetime.now(timezone.utc),
        metrics=metrics,
        overall_score=72.5,
        target_accent_id="general_american",
        assessment_type="baseline",
        audio_clip_id="audio_main",
        is_audio_available=is_audio_available,
    )


def make_dispute_service(**kwargs) -> ScoreDisputeService:
    return ScoreDisputeService(store=InMemoryKvStore(), **kwargs)


@pytest.mark.asyncio
async def test_dispute_available_on_every_metric():
    service = make_dispute_service()
    assessment = make_assessment_result()

    # Dispute pronunciation
    res1 = await service.submit_dispute(
        user_id="user_1",
        assessment=assessment,
        metric_name="pronunciation",
        reason=DisputeReason.BACKGROUND_NOISE.value,
    )
    assert res1.success is True
    assert res1.dispute.metric_name == "pronunciation"
    assert res1.dispute.original_score == 70.0

    # Dispute word_stress (another metric)
    res2 = await service.submit_dispute(
        user_id="user_1",
        assessment=assessment,
        metric_name="word_stress",
        reason=DisputeReason.UNFAIR_PENALTY.value,
    )
    assert res2.success is True
    assert res2.dispute.metric_name == "word_stress"
    assert res2.dispute.original_score == 65.0

    # Dispute overall
    res3 = await service.submit_dispute(
        user_id="user_1",
        assessment=assessment,
        metric_name="overall",
        reason=DisputeReason.MISHEARD_WORD.value,
    )
    assert res3.success is True
    assert res3.dispute.metric_name == "overall"
    assert res3.dispute.original_score == 72.5


@pytest.mark.asyncio
async def test_no_auto_correction_without_review():
    service = make_dispute_service()
    assessment = make_assessment_result()

    res = await service.submit_dispute(
        user_id="user_1",
        assessment=assessment,
        metric_name="pronunciation",
        reason=DisputeReason.UNFAIR_PENALTY.value,
    )
    # Status MUST remain pending_review, revised_score MUST be None initially!
    assert res.dispute.status == DisputeStatus.PENDING_REVIEW.value
    assert res.dispute.revised_score is None

    # Resolve with manual/model review
    resolved = await service.resolve_dispute(
        dispute_id=res.dispute.dispute_id,
        new_status=DisputeStatus.RESOLVED_SCORE_ADJUSTED.value,
        revised_score=85.0,
        review_notes="Re-scored: ambient noise filtered out.",
    )
    assert resolved.status == DisputeStatus.RESOLVED_SCORE_ADJUSTED.value
    assert resolved.revised_score == 85.0
    assert "85.0" in (resolved.notification or "")


@pytest.mark.asyncio
async def test_e01_high_volume_disputes_auto_flags_drill():
    service = make_dispute_service(high_volume_threshold=3)
    assessment = make_assessment_result(assessment_id="drill_popular")

    # User 1 disputes
    r1 = await service.submit_dispute("u1", assessment, "pronunciation", DisputeReason.BACKGROUND_NOISE.value)
    assert r1.auto_flagged_for_content_team is False

    # User 2 disputes
    r2 = await service.submit_dispute("u2", assessment, "pronunciation", DisputeReason.BACKGROUND_NOISE.value)
    assert r2.auto_flagged_for_content_team is False

    # User 3 disputes -> Hits threshold 3!
    r3 = await service.submit_dispute("u3", assessment, "pronunciation", DisputeReason.BACKGROUND_NOISE.value)
    assert r3.auto_flagged_for_content_team is True
    assert "Auto-flagged for content team" in (r3.notice or "")

    # Check previously submitted dispute is also flagged
    d1 = await service.get_dispute(r1.dispute.dispute_id)
    assert d1.auto_flagged_for_content_team is True


@pytest.mark.asyncio
async def test_e02_rate_limit_per_user_per_day():
    service = make_dispute_service(max_disputes_per_day=2)
    assessment = make_assessment_result()

    # Dispute 1
    r1 = await service.submit_dispute("u1", assessment, "pronunciation", DisputeReason.MISHEARD_WORD.value)
    assert r1.success is True
    assert r1.remaining_allowance == 1

    # Dispute 2
    r2 = await service.submit_dispute("u1", assessment, "clarity", DisputeReason.MISHEARD_WORD.value)
    assert r2.success is True
    assert r2.remaining_allowance == 0

    # Dispute 3 -> exceeds max daily allowance of 2!
    r3 = await service.submit_dispute("u1", assessment, "intonation", DisputeReason.MISHEARD_WORD.value)
    assert r3.success is False
    assert r3.remaining_allowance == 0
    assert "Daily dispute limit reached" in (r3.error_message or "")


@pytest.mark.asyncio
async def test_e03_dispute_on_deleted_audio_offers_reassessment():
    service = make_dispute_service()
    assessment_deleted_audio = make_assessment_result(is_audio_available=False)

    res = await service.submit_dispute(
        user_id="u1",
        assessment=assessment_deleted_audio,
        metric_name="pronunciation",
        reason=DisputeReason.BACKGROUND_NOISE.value,
    )

    assert res.success is False
    assert res.offer_reassessment is True
    assert "auto-purged per retention policy" in (res.error_message or "")
