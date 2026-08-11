"""
Tests for shared accent profile & scoring pipeline (lib/accent_assessment/profile_pipeline.py).
"""

from datetime import datetime, timezone

import pytest

from lib.accent_assessment.profile_pipeline import (
    AccentAssessmentResult,
    AccentProfile,
    AccentProfilePipelineService,
    ScoredMetric,
    calculate_overall_accent_score,
)
from lib.kv_store import InMemoryKvStore


@pytest.mark.asyncio
async def test_calculate_overall_accent_score():
    metrics = {
        "pronunciation": ScoredMetric("pronunciation", 80.0),
        "word_stress": ScoredMetric("word_stress", 90.0),
        "intonation": ScoredMetric("intonation", 70.0),
        "clarity": ScoredMetric("clarity", 80.0),
    }
    assert calculate_overall_accent_score(metrics) == 80.0


@pytest.mark.asyncio
async def test_initial_baseline_creation_and_retrieval():
    service = AccentProfilePipelineService(store=InMemoryKvStore())
    now = datetime.now(timezone.utc)
    profile = await service.create_initial_baseline(
        user_id="user_123",
        metric_scores={"pronunciation": 75.0, "clarity": 85.0},
        target_accent_id="british_rp",
        timestamp=now,
    )

    assert profile.user_id == "user_123"
    assert profile.target_accent_id == "british_rp"
    assert len(profile.baselines_history) == 1
    assert profile.current_baseline is not None
    assert profile.current_baseline.overall_score == 80.0
    assert profile.current_baseline.target_accent_id == "british_rp"

    retrieved = await service.get_profile("user_123")
    assert retrieved is not None
    assert retrieved.user_id == "user_123"
    assert len(retrieved.baselines_history) == 1
