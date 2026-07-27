"""
Pronunciation engine outage & timeout fallback (Story 3).

A reliability wrapper AROUND the shared PronunciationPipeline
(pronunciation_pipeline.py) - it does not score anything itself. It only
governs how a scoring *call* is submitted: timeout, backoff/retry,
outage queueing, corrupted-response handling, and background completion
while the user has navigated away. The actual word-level scoring for
every code path here still comes from PronunciationPipeline.score_sentence
(directly, or via accessibility_profile.score_with_accessibility).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable, Dict, List, Optional

from lib.pronunciation_coach.pronunciation_pipeline import SentenceScoreResult

logger = logging.getLogger(__name__)


class AttemptStatus(str, Enum):
    SCORED = "scored"
    RETRYING = "retrying"                # E-01: transient, still auto-retrying, no message shown yet
    OUTAGE_QUEUED = "outage_queued"       # E-02: service unreachable after retries, queued in background
    HARD_FAILURE = "hard_failure"         # explicit service error (not just slow/down) - manual retry needed
    CORRUPTED_DISCARDED = "corrupted_discarded"  # E-03


class ScoringServiceError(Exception):
    """Raised by a score_callable to signal a backend scoring failure."""

    def __init__(self, message: str, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable  # True: service down/unreachable. False: explicit error response.


class CorruptedResponseError(Exception):
    """Raised by a score_callable when the payload couldn't even be parsed."""


@dataclass(frozen=True)
class ReliabilityConfig:
    """Named, overridable timeout/retry constants. All UNCALIBRATED defaults."""

    per_attempt_timeout_seconds: float = 8.0
    max_auto_retries: int = 2
    retry_backoff_seconds: tuple = (2.0, 5.0)  # len must equal max_auto_retries

    def __post_init__(self):
        if len(self.retry_backoff_seconds) != self.max_auto_retries:
            raise ValueError("retry_backoff_seconds must have exactly max_auto_retries entries")


# User-facing copy kept as named constants rather than inlined strings, so
# product/UX can change wording without touching retry logic.
OUTAGE_MESSAGE = "We'll save your attempt and retry shortly."
HARD_FAILURE_MESSAGE = "We couldn't score that attempt. Please try again."
CORRUPTED_MESSAGE = "That attempt didn't come back clean - please re-record."


@dataclass
class SubmissionOutcome:
    attempt_id: str
    status: AttemptStatus
    result: Optional[SentenceScoreResult] = None
    message: Optional[str] = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PendingAttemptStore:
    """
    E-02: preserves recorded audio locally instead of discarding it when
    the service is fully unreachable, and holds it for background retry.
    In-memory, following the same accumulate-in-memory pattern as
    confidence.py's session_history (no DB layer in this module set).
    """

    def __init__(self):
        self._pending: Dict[str, List[dict]] = {}

    def enqueue(self, user_id: str, attempt_id: str, audio_ref: str):
        self._pending.setdefault(user_id, []).append(
            {"attempt_id": attempt_id, "audio_ref": audio_ref, "queued_at": datetime.now(timezone.utc)}
        )

    def list_pending(self, user_id: str) -> List[dict]:
        return list(self._pending.get(user_id, []))

    def remove(self, user_id: str, attempt_id: str):
        self._pending[user_id] = [p for p in self._pending.get(user_id, []) if p["attempt_id"] != attempt_id]


class PendingResultsBoard:
    """
    E-05: when the user navigates away mid-scoring, the attempt keeps
    scoring in the background; the outcome is posted here and surfaced as
    a badge/notification the next time the user checks in.
    """

    def __init__(self):
        self._board: Dict[str, List[SubmissionOutcome]] = {}

    def post(self, user_id: str, outcome: SubmissionOutcome):
        self._board.setdefault(user_id, []).append(outcome)

    def get_and_clear(self, user_id: str) -> List[SubmissionOutcome]:
        pending = self._board.get(user_id, [])
        self._board[user_id] = []
        return pending


def _is_valid_result(result: Optional[SentenceScoreResult]) -> bool:
    """E-03: sanity-check a scoring payload before trusting it as a real score."""
    if result is None or not result.words:
        return False
    return 0.0 <= result.fluency_score <= 100.0


class PronunciationSubmissionManager:
    """
    Submits one pronunciation-scoring attempt with timeout/backoff/outage
    handling. Previous attempts' SentenceScoreResults are owned by the
    caller and never touched by this class (E-04: an outage mid-streak
    only affects the pending attempt being submitted right now).
    """

    def __init__(
        self,
        config: Optional[ReliabilityConfig] = None,
        pending_attempts: Optional[PendingAttemptStore] = None,
        results_board: Optional[PendingResultsBoard] = None,
    ):
        self.config = config or ReliabilityConfig()
        self.pending_attempts = pending_attempts or PendingAttemptStore()
        self.results_board = results_board or PendingResultsBoard()

    async def submit(
        self,
        user_id: str,
        attempt_id: str,
        audio_ref: str,
        score_callable: Callable[[], Awaitable[SentenceScoreResult]],
    ) -> SubmissionOutcome:
        """
        Attempt to score once, auto-retrying transient timeouts/outages up
        to config.max_auto_retries times with backoff (E-01) before
        surfacing anything to the user.
        """
        last_error: Optional[BaseException] = None

        for attempt_number in range(self.config.max_auto_retries + 1):
            try:
                result = await asyncio.wait_for(
                    score_callable(), timeout=self.config.per_attempt_timeout_seconds
                )
            except CorruptedResponseError:
                logger.warning("Attempt %s: corrupted response, discarding", attempt_id)
                return SubmissionOutcome(
                    attempt_id=attempt_id,
                    status=AttemptStatus.CORRUPTED_DISCARDED,
                    message=CORRUPTED_MESSAGE,
                )
            except (asyncio.TimeoutError, ScoringServiceError) as exc:
                last_error = exc
                is_last_attempt = attempt_number == self.config.max_auto_retries
                unreachable = isinstance(exc, asyncio.TimeoutError) or getattr(exc, "unreachable", False)

                if not is_last_attempt:
                    logger.info(
                        "Attempt %s: transient failure (%s), retrying in %.1fs (%d/%d)",
                        attempt_id, exc, self.config.retry_backoff_seconds[attempt_number],
                        attempt_number + 1, self.config.max_auto_retries,
                    )
                    await asyncio.sleep(self.config.retry_backoff_seconds[attempt_number])
                    continue

                if unreachable:
                    # E-02: Full Service Outage.
                    self.pending_attempts.enqueue(user_id, attempt_id, audio_ref)
                    return SubmissionOutcome(
                        attempt_id=attempt_id,
                        status=AttemptStatus.OUTAGE_QUEUED,
                        message=OUTAGE_MESSAGE,
                    )

                # Explicit service error, not a full outage: hard failure,
                # inform + require manual retry, do not silently queue.
                return SubmissionOutcome(
                    attempt_id=attempt_id,
                    status=AttemptStatus.HARD_FAILURE,
                    message=HARD_FAILURE_MESSAGE,
                )
            else:
                if not _is_valid_result(result):
                    logger.warning("Attempt %s: malformed/partial result, discarding", attempt_id)
                    return SubmissionOutcome(
                        attempt_id=attempt_id,
                        status=AttemptStatus.CORRUPTED_DISCARDED,
                        message=CORRUPTED_MESSAGE,
                    )
                return SubmissionOutcome(attempt_id=attempt_id, status=AttemptStatus.SCORED, result=result)

        # Unreachable in practice (loop always returns/raises above), kept
        # for type-checker completeness.
        raise RuntimeError(f"submit() exhausted retries without resolving: last_error={last_error}")

    def submit_background(
        self,
        user_id: str,
        attempt_id: str,
        audio_ref: str,
        score_callable: Callable[[], Awaitable[SentenceScoreResult]],
    ) -> "asyncio.Task[SubmissionOutcome]":
        """
        E-05: fire off scoring as a background task that keeps running
        (and posts its outcome to results_board) even if the caller/UI
        goes away. Caller polls results_board.get_and_clear(user_id) on
        return to surface a badge/notification.
        """

        async def _run():
            outcome = await self.submit(user_id, attempt_id, audio_ref, score_callable)
            self.results_board.post(user_id, outcome)
            return outcome

        return asyncio.create_task(_run())

    async def retry_queued_outages(
        self,
        user_id: str,
        score_callable_factory: Callable[[str], Callable[[], Awaitable[SentenceScoreResult]]],
    ) -> List[SubmissionOutcome]:
        """
        Background-worker entry point: re-attempt every attempt queued by
        E-02 for this user. `score_callable_factory` builds a fresh
        score_callable for a given audio_ref (the caller knows how to turn
        a stored audio_ref back into a scoring call).
        """
        outcomes = []
        for pending in self.pending_attempts.list_pending(user_id):
            outcome = await self.submit(
                user_id, pending["attempt_id"], pending["audio_ref"], score_callable_factory(pending["audio_ref"])
            )
            if outcome.status != AttemptStatus.OUTAGE_QUEUED:
                self.pending_attempts.remove(user_id, pending["attempt_id"])
            outcomes.append(outcome)
        return outcomes
