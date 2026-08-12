"""
Script Practice Confidence Score service — PSA-US-05 (US-157).

Reads a rewrite/script aloud twice and reports the confidence gain:

  start    -> create a practice for a given script
  baseline -> score the cold first read (before). Re-recordable — a fresh
              baseline resets the final-read state.
  after    -> score the post-practice read (after) against the CURRENT baseline;
              gain = after - before. Re-recordable — each success appends a new
              history row (append-only), so prior results are preserved.
  history  -> paginated past evaluations + in-DB average gain.

Every read's metrics (confidence/fluency/vocabulary/pronunciation) reuse the
EXISTING audio pipeline unchanged (session_scorer.score_audio_session +
confidence_engine) so all reads share one yardstick. The live baseline read is
persisted (transcript + duration), so re-scoring it during a final evaluation
needs no extra columns. Isolated tables; no writes to any other feature.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import Depends
from prisma import Json

from lib.confidence_engine import ConfidenceScoreEngine
from lib.prisma_client import db
from lib import relevance
from lib.session_scorer import AudioFeatures, ScoredSession, score_audio_session
from middlewares.auth_middleware import require_auth
from schemas.script_practice_schemas import (
    AfterResponse,
    BaselineResponse,
    HistoryEntry,
    PaginatedHistoryResponse,
    PracticeSummary,
    ReadMetrics,
    SpokenAttempt,
    StartPracticeRequest,
    StartPracticeResponse,
)
from utils.feature_errors import InvalidSubmissionError, SessionNotFoundError

logger = logging.getLogger(__name__)

MIN_SPOKEN_WORDS = 3          # E-03: anything shorter is "insufficient practice"
DEFAULT_HISTORY_LIMIT = 5     # the panel shows 5 at a time
MAX_HISTORY_LIMIT = 50


# ── scoring ───────────────────────────────────────────────────────────────────
def _script_coverage(script: str, transcript: str) -> float:
    """Fraction of the script's content words the read actually contains, 0-1.

    Deterministic and offline — this is "did you read this passage", not "was your answer
    relevant", so it needs word overlap rather than the LLM judge. Below 30% the read is
    treated as not a read of this script at all.
    """
    expected = relevance.content_words(relevance.tokenize(script))
    if not expected:
        return 1.0
    spoken = set(relevance.tokenize(transcript))
    ratio = len(expected & spoken) / len(expected)
    return 0.0 if ratio < 0.30 else ratio
def _score_read(transcript: str, duration_seconds: float, script: Optional[str] = None) -> ReadMetrics:
    """One spoken read -> full delivery metrics, via the existing audio pipeline.

    Scored strictly (no floors). `script`, when supplied, gates the read on whether it is
    actually a read of THAT script rather than of something else: this feature reports a
    before/after gain, and reading a different, easier passage the second time would
    otherwise register as improvement.
    """
    features = AudioFeatures(transcript=transcript, duration_seconds=duration_seconds)
    scored = score_audio_session(features, strict=True)
    if script:
        coverage = _script_coverage(script, transcript)
        scored = ScoredSession(
            fluency_score=round(scored.fluency_score * coverage, 2),
            vocabulary_score=round(scored.vocabulary_score * coverage, 2),
            pronunciation_score=(round(scored.pronunciation_score * coverage, 2)
                                 if scored.pronunciation_score is not None else None),
            is_text_only=scored.is_text_only,
            delivery=scored.delivery,
        )
    confidence = ConfidenceScoreEngine().calculate_session_confidence(
        scored.to_session_score(is_complete=True)
    )
    return ReadMetrics(
        confidence=confidence,
        fluency=scored.fluency_score,
        vocabulary=scored.vocabulary_score,
        pronunciation=scored.pronunciation_score,
    )


def _build_feedback(before: ReadMetrics, after: ReadMetrics) -> str:
    """Deterministic before/after comparison — no LLM, so it's fast and offline-safe."""
    bits = []

    def phrase(label: str, delta: float, unit_up: str, unit_down: str) -> None:
        if delta > 1.5:
            bits.append(f"{label} {unit_up} (+{round(delta, 1)})")
        elif delta < -1.5:
            bits.append(f"{label} {unit_down} ({round(delta, 1)})")

    phrase("confidence", after.confidence - before.confidence, "rose", "dipped")
    phrase("fluency", after.fluency - before.fluency, "improved", "slipped")
    if before.pronunciation is not None and after.pronunciation is not None:
        phrase("clarity", after.pronunciation - before.pronunciation, "sharper", "less clear")

    if not bits:
        return "Very consistent delivery — your second read held steady. Keep practicing to push higher."
    lead = "Nice progress" if after.confidence >= before.confidence else "Keep at it"
    return f"{lead}: " + ", ".join(bits) + "."


def _metrics_from_json(raw) -> ReadMetrics:
    data: Dict = raw if isinstance(raw, dict) else {}
    return ReadMetrics(
        confidence=float(data.get("confidence", 0.0)),
        fluency=float(data.get("fluency", 0.0)),
        vocabulary=float(data.get("vocabulary", 0.0)),
        pronunciation=data.get("pronunciation"),
    )


# ── validation ────────────────────────────────────────────────────────────────
def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _validate_attempt(attempt: SpokenAttempt) -> None:
    if _word_count(attempt.transcript) < MIN_SPOKEN_WORDS or attempt.duration_seconds <= 0:
        # E-02 (audio failure -> empty transcript) and E-03 (too short) both land here.
        raise InvalidSubmissionError(
            "That read was too short to measure. Please read the whole script aloud and try again."
        )


async def _owned_session(session_id: str, user_id: str):
    session = await db.scriptpracticesession.find_unique(where={"id": session_id})
    if not session or session.userId != user_id:
        raise SessionNotFoundError("Practice session not found")
    return session


# ── controllers ───────────────────────────────────────────────────────────────
async def start_practice(
    payload: StartPracticeRequest, user_id: str = Depends(require_auth)
) -> StartPracticeResponse:
    if _word_count(payload.script) < MIN_SPOKEN_WORDS:
        raise InvalidSubmissionError("Please provide a script with at least a short sentence.")
    session = await db.scriptpracticesession.create(
        data={
            "userId": user_id,
            "scriptText": payload.script,
            "context": payload.context or None,
            "status": "awaiting_baseline",
        }
    )
    return StartPracticeResponse(session_id=session.id, status=session.status)


async def submit_baseline(
    session_id: str, payload: SpokenAttempt, user_id: str = Depends(require_auth)
) -> BaselineResponse:
    session = await _owned_session(session_id, user_id)
    _validate_attempt(payload)

    metrics = _score_read(payload.transcript, payload.duration_seconds, session.scriptText)
    # Re-record support: a new baseline overwrites the old one AND resets the final read
    # (any prior evaluation depended on the old baseline). Status returns to "practicing".
    await db.scriptpracticesession.update(
        where={"id": session_id},
        data={
            "status": "practicing",
            "baselineConfidence": metrics.confidence,
            "baselineTranscript": payload.transcript,
            "baselineDuration": payload.duration_seconds,
            "afterConfidence": None,
            "afterTranscript": None,
            "afterDuration": None,
            "confidenceGain": None,
            "completedAt": None,
        },
    )
    return BaselineResponse(
        session_id=session_id,
        baseline_confidence=metrics.confidence,
        metrics=metrics,
        status="practicing",
    )


async def submit_after(
    session_id: str, payload: SpokenAttempt, user_id: str = Depends(require_auth)
) -> AfterResponse:
    session = await _owned_session(session_id, user_id)
    # E-01: no baseline -> no gain can be computed.
    if session.baselineConfidence is None or not session.baselineTranscript:
        raise InvalidSubmissionError("Record your baseline read first, before the after read.")
    _validate_attempt(payload)

    # Re-score the CURRENT baseline from its stored read, so metrics/feedback always
    # compare against the latest baseline (correct after a baseline re-record).
    baseline_metrics = _score_read(
        session.baselineTranscript, session.baselineDuration or 0.0, session.scriptText
    )
    after_metrics = _score_read(payload.transcript, payload.duration_seconds, session.scriptText)
    gain = round(after_metrics.confidence - baseline_metrics.confidence, 2)
    feedback = _build_feedback(baseline_metrics, after_metrics)
    now = datetime.now(timezone.utc)

    # Update the live session's current final read...
    await db.scriptpracticesession.update(
        where={"id": session_id},
        data={
            "status": "completed",
            "afterConfidence": after_metrics.confidence,
            "afterTranscript": payload.transcript,
            "afterDuration": payload.duration_seconds,
            "confidenceGain": gain,
            "completedAt": now,
        },
    )
    # ...and append an immutable history entry (re-records preserve prior results).
    history = await db.scriptpracticehistory.create(
        data={
            "userId": user_id,
            "sessionId": session_id,
            "scriptText": session.scriptText,
            "context": session.context,
            "baselineConfidence": baseline_metrics.confidence,
            "afterConfidence": after_metrics.confidence,
            "confidenceGain": gain,
            "baselineMetrics": Json(baseline_metrics.model_dump()),
            "afterMetrics": Json(after_metrics.model_dump()),
            "feedback": feedback,
        }
    )
    return AfterResponse(
        session_id=session_id,
        baseline_confidence=baseline_metrics.confidence,
        after_confidence=after_metrics.confidence,
        confidence_gain=gain,
        improved=gain > 0,
        baseline_metrics=baseline_metrics,
        after_metrics=after_metrics,
        feedback=feedback,
        history_id=history.id,
        status="completed",
    )


def _to_history_entry(h) -> HistoryEntry:
    return HistoryEntry(
        id=h.id,
        script=h.scriptText,
        context=h.context,
        baseline_confidence=h.baselineConfidence,
        after_confidence=h.afterConfidence,
        confidence_gain=h.confidenceGain,
        baseline_metrics=_metrics_from_json(h.baselineMetrics),
        after_metrics=_metrics_from_json(h.afterMetrics),
        feedback=h.feedback,
        created_at=h.createdAt.isoformat(),
    )


async def get_history(
    offset: int = 0,
    limit: int = DEFAULT_HISTORY_LIMIT,
    user_id: str = Depends(require_auth),
) -> PaginatedHistoryResponse:
    """Server-side paginated history (newest first). Never loads the whole table:
    a COUNT + AVG aggregate for the headline, plus one bounded page."""
    offset = max(0, offset)
    limit = max(1, min(limit, MAX_HISTORY_LIMIT))

    total = await db.scriptpracticehistory.count(where={"userId": user_id})
    rows = await db.scriptpracticehistory.find_many(
        where={"userId": user_id},
        order={"createdAt": "desc"},
        skip=offset,
        take=limit,
    )
    avg_gain: Optional[float] = None
    if total:
        agg = await db.query_raw(
            'SELECT AVG("confidenceGain") AS avg FROM script_practice_history WHERE "userId" = $1',
            user_id,
        )
        raw_avg = agg[0]["avg"] if agg else None
        avg_gain = round(float(raw_avg), 2) if raw_avg is not None else None

    return PaginatedHistoryResponse(
        entries=[_to_history_entry(h) for h in rows],
        total=total,
        offset=offset,
        limit=limit,
        completed_count=total,
        average_gain=avg_gain,
    )


async def get_practice(session_id: str, user_id: str = Depends(require_auth)) -> PracticeSummary:
    session = await _owned_session(session_id, user_id)
    return PracticeSummary(
        session_id=session.id,
        script=session.scriptText,
        context=session.context,
        status=session.status,
        baseline_confidence=session.baselineConfidence,
        after_confidence=session.afterConfidence,
        confidence_gain=session.confidenceGain,
        created_at=session.createdAt.isoformat(),
        completed_at=session.completedAt.isoformat() if session.completedAt else None,
    )
