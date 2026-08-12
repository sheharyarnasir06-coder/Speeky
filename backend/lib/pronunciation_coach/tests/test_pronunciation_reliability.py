"""
Tests for Story 3 (lib/pronunciation_coach/pronunciation_reliability.py).

No pytest-asyncio plugin dependency is assumed beyond this project's own
pyproject.toml config (asyncio_mode = "auto"), so async scenarios use
plain async def test_... functions.
"""

import asyncio

import pytest

from lib.pronunciation_coach.pronunciation_pipeline import ColorTier, SentenceScoreResult, WordScoreResult
from lib.pronunciation_coach.pronunciation_reliability import (
    AttemptStatus,
    CorruptedResponseError,
    PendingAttemptStore,
    PendingResultsBoard,
    PronunciationSubmissionManager,
    ReliabilityConfig,
    ScoringServiceError,
)


def _fast_config(**overrides):
    defaults = dict(per_attempt_timeout_seconds=0.2, max_auto_retries=2, retry_backoff_seconds=(0.01, 0.01))
    defaults.update(overrides)
    return ReliabilityConfig(**defaults)


def _valid_result():
    return SentenceScoreResult(
        target_sentence="hello",
        words=[WordScoreResult(index=0, target_word="hello", tier=ColorTier.GREEN, final_score=95.0)],
        fluency_score=100.0,
    )


async def test_immediate_success():
    manager = PronunciationSubmissionManager(config=_fast_config())

    async def score_fn():
        return _valid_result()

    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.SCORED
    assert outcome.result is not None


async def test_e01_transient_timeout_auto_retries_then_succeeds():
    calls = {"count": 0}

    async def score_fn():
        calls["count"] += 1
        if calls["count"] < 2:
            raise asyncio.TimeoutError()
        return _valid_result()

    manager = PronunciationSubmissionManager(config=_fast_config())
    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.SCORED
    assert calls["count"] == 2  # one failure, one successful retry, no message ever needed


async def test_e02_full_outage_queues_audio_and_message():
    async def score_fn():
        raise asyncio.TimeoutError()

    pending_store = PendingAttemptStore()
    manager = PronunciationSubmissionManager(config=_fast_config(), pending_attempts=pending_store)

    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.OUTAGE_QUEUED
    assert outcome.message is not None
    queued = pending_store.list_pending("u1")
    assert len(queued) == 1
    assert queued[0]["audio_ref"] == "audio://a1"


async def test_e02_unreachable_service_error_also_queues():
    async def score_fn():
        raise ScoringServiceError("connection refused", unreachable=True)

    manager = PronunciationSubmissionManager(config=_fast_config())
    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.OUTAGE_QUEUED


async def test_hard_failure_for_explicit_non_outage_error():
    async def score_fn():
        raise ScoringServiceError("500 internal error", unreachable=False)

    manager = PronunciationSubmissionManager(config=_fast_config())
    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.HARD_FAILURE
    assert "try again" in outcome.message.lower()


async def test_e03_corrupted_response_discarded_not_shown_as_score():
    async def score_fn():
        raise CorruptedResponseError("malformed payload")

    manager = PronunciationSubmissionManager(config=_fast_config())
    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.CORRUPTED_DISCARDED
    assert outcome.result is None


async def test_e03_empty_result_treated_as_corrupted():
    async def score_fn():
        return SentenceScoreResult(target_sentence="hello", words=[], fluency_score=100.0)

    manager = PronunciationSubmissionManager(config=_fast_config())
    outcome = await manager.submit("u1", "a1", "audio://a1", score_fn)

    assert outcome.status == AttemptStatus.CORRUPTED_DISCARDED


async def test_e04_outage_does_not_touch_previous_results():
    """Simulate a prior scored attempt, then an outage on a new attempt: the old result object is untouched."""
    previous_result = _valid_result()
    previous_snapshot = SentenceScoreResult(**vars(previous_result))

    async def failing_score_fn():
        raise asyncio.TimeoutError()

    manager = PronunciationSubmissionManager(config=_fast_config())
    await manager.submit("u1", "a2", "audio://a2", failing_score_fn)

    assert previous_result == previous_snapshot


async def test_e05_background_submission_posts_to_results_board():
    board = PendingResultsBoard()
    manager = PronunciationSubmissionManager(config=_fast_config(), results_board=board)

    async def score_fn():
        return _valid_result()

    task = manager.submit_background("u1", "a1", "audio://a1", score_fn)
    await task

    pending = board.get_and_clear("u1")
    assert len(pending) == 1
    assert pending[0].status == AttemptStatus.SCORED
    assert board.get_and_clear("u1") == []  # cleared after read


async def test_retry_queued_outages_removes_from_queue_on_success():
    pending_store = PendingAttemptStore()
    pending_store.enqueue("u1", "a1", "audio://a1")
    manager = PronunciationSubmissionManager(config=_fast_config(), pending_attempts=pending_store)

    def factory(audio_ref):
        async def score_fn():
            return _valid_result()

        return score_fn

    outcomes = await manager.retry_queued_outages("u1", factory)

    assert len(outcomes) == 1
    assert outcomes[0].status == AttemptStatus.SCORED
    assert pending_store.list_pending("u1") == []


def test_reliability_config_rejects_mismatched_backoff_length():
    with pytest.raises(ValueError):
        ReliabilityConfig(max_auto_retries=2, retry_backoff_seconds=(1.0,))
