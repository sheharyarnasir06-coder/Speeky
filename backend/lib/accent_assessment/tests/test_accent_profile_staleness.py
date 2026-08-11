"""
Tests for ACC-US-05 / US-82 (lib/accent_assessment/accent_profile_staleness.py).
"""

from datetime import datetime, timedelta, timezone

import pytest

from lib.accent_assessment.accent_profile_staleness import (
    DEFAULT_DISMISS_BACKOFF_DAYS,
    DEFAULT_INACTIVITY_RESET_THRESHOLD_DAYS,
    DEFAULT_STALENESS_THRESHOLD_DAYS,
    AccentProfileStalenessService,
)
from lib.accent_assessment.profile_pipeline import AccentProfilePipelineService
from lib.kv_store import InMemoryKvStore


def make_staleness_service() -> AccentProfileStalenessService:
    store = InMemoryKvStore()
    pipeline_service = AccentProfilePipelineService(store=store)
    return AccentProfileStalenessService(pipeline_service=pipeline_service)


@pytest.mark.asyncio
async def test_staleness_detection_60_days():
    service = make_staleness_service()
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=65)

    # Initial baseline 65 days ago
    await service.pipeline_service.create_initial_baseline(
        user_id="u1",
        metric_scores={"pronunciation": 80.0, "clarity": 85.0},
        timestamp=t0,
    )

    info = await service.check_staleness_on_login("u1", login_time=now)
    assert info.is_stale is True
    assert info.should_prompt is True
    assert info.profile_age_days == 65
    assert "Your accent profile is 65 days old" in (info.prompt_message or "")


@pytest.mark.asyncio
async def test_history_preserved_not_overwritten():
    service = make_staleness_service()
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=70)

    # Step 1: Initial baseline 70 days ago
    await service.pipeline_service.create_initial_baseline(
        user_id="u1",
        metric_scores={"pronunciation": 70.0},
        timestamp=t0,
    )

    # Step 2: Fresh re-baseline today
    rebaseline_res = await service.execute_rebaseline(
        user_id="u1",
        metric_scores={"pronunciation": 85.0},
        assessment_time=now,
    )

    assert rebaseline_res.overall_score == 85.0

    # Verify history has BOTH entries
    profile = await service.pipeline_service.get_profile("u1")
    assert profile is not None
    assert len(profile.baselines_history) == 2
    assert profile.baselines_history[0].overall_score == 70.0
    assert profile.baselines_history[0].is_historical is True
    assert profile.baselines_history[1].overall_score == 85.0


@pytest.mark.asyncio
async def test_e01_user_dismisses_repeatedly_frequency_backoff():
    service = make_staleness_service()
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=70)

    await service.pipeline_service.create_initial_baseline(
        user_id="u1",
        metric_scores={"pronunciation": 70.0},
        timestamp=t0,
    )

    # Dismiss 3 times
    for i in range(3):
        await service.dismiss_prompt("u1", dismiss_time=now - timedelta(days=1))

    info = await service.check_staleness_on_login("u1", login_time=now)
    assert info.prompt_frequency == "weekly"
    # Dismissed 1 day ago, backoff is 7 days -> should NOT prompt on every login
    assert info.should_prompt is False


@pytest.mark.asyncio
async def test_e02_rebaseline_requested_too_soon_labeled_manual_refresh():
    service = make_staleness_service()
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=5)  # only 5 days ago

    await service.pipeline_service.create_initial_baseline(
        user_id="u1",
        metric_scores={"pronunciation": 70.0},
        timestamp=t0,
    )

    res = await service.execute_rebaseline(
        user_id="u1",
        metric_scores={"pronunciation": 75.0},
        assessment_time=now,
    )

    assert res.assessment_type == "manual_refresh"
    assert "manual refresh" in (res.notice or "")


@pytest.mark.asyncio
async def test_e03_inactivity_exceeds_1_year_reset():
    service = make_staleness_service()
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=400)  # > 365 days

    await service.pipeline_service.create_initial_baseline(
        user_id="u1",
        metric_scores={"pronunciation": 60.0},
        timestamp=t0,
    )

    info = await service.check_staleness_on_login("u1", login_time=now)
    assert info.suggested_rebaseline_type == "brand_new_baseline"
    assert "Inactivity exceeds 1 year" in (info.notice or "")

    res = await service.execute_rebaseline(
        user_id="u1",
        metric_scores={"pronunciation": 80.0},
        assessment_time=now,
    )

    assert res.assessment_type == "brand_new_baseline"
    profile = await service.pipeline_service.get_profile("u1")
    assert profile.is_reset_baseline is True
