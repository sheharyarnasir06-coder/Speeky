"""
Progress Dashboard Tracking Service (PDG-US-10 & PDG-US-14)

Aggregates data across all completed learning sessions (BaselineAssessment, CoachingSession,
ScenarioSession, PublicSpeakingSession, AccentAssessment, PronunciationAttempt) into a visual,
time-series progress dashboard.

Features & Exception Handling:
  - Immediate post-session update (computed on read, no stale caching during normal operation).
  - Confidence Score returned as the central, top-line primary metric.
  - Time-series data points shaped for visual graph trend lines.
  - E-01 (Data Sync Failure): Graceful fallback to last known good snapshot with sync_status="stale".
  - E-02 (Empty State - Day 1): Zero-state payload with motivational prompt for day-1 users.
  - E-03 (Corrupted Session Data): Drops outlier scores (> 100 or < 0) from visual aggregates and flags the row.
  - E-04 (Streak Calculation): Rolling 24-48 hour UTC window calculation to prevent timezone breaks.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends
from fastapi.responses import JSONResponse
from prisma import Json

from lib import kv_store
from lib.prisma_client import db
from middlewares.auth_middleware import require_auth
from schemas.progress_dashboard_schemas import (
    PrimaryMetricSchema,
    ProgressDashboardMetricsSchema,
    ProgressDashboardResponseSchema,
    TrendPointSchema,
)

logger = logging.getLogger(__name__)

DASHBOARD_SNAPSHOT_NS = "dashboard_snapshots"
MAX_DAILY_VOCAB_GROWTH = 15

DAY1_MOTIVATIONAL_PROMPT = "Complete your first session to see your progress growth!"
SYNC_STALE_MESSAGE = "Syncing recent data... Unable to reach server, showing last-known-good metrics."

# PDG-US-14 copy used by the legacy /overview payload (Vocabulary Growth panel).
_EMPTY_STATE_MESSAGE = "Complete a Scenario to start collecting words!"
_ZERO_GROWTH_MESSAGE = "Great consistency! Try a new Scenario to discover advanced words."


async def _is_db_connected() -> bool:
    try:
        return db.is_connected()
    except Exception:
        return False


def _validate_score(score: Optional[float]) -> Tuple[Optional[float], bool]:
    """
    E-03 Corrupted Session Data Check:
    Validates a score. If score is out of bounds (< 0 or > 100), drops it (returns None)
    and flags it as an outlier.
    """
    if score is None:
        return None, False
    try:
        val = float(score)
        if val < 0.0 or val > 100.0:
            return None, True  # Outlier dropped!
        return round(val, 2), False
    except (ValueError, TypeError):
        return None, True


async def _flag_outlier_row(prisma_model, row_id: str, flag_field: str, offending_fields: List[str]) -> None:
    """
    E-03 (continued): actually persists the outlier flag onto the source row instead of
    only counting it in-memory, so the flagged session is visible for review later
    (appends rather than overwrites, since a row could be flagged more than once).
    """
    try:
        current = await prisma_model.find_unique(where={"id": row_id})
        if not current:
            return
        existing = list(getattr(current, flag_field) or [])
        existing.append({
            "type": "outlier_score",
            "fields": offending_fields,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
            "note": "Score outside the valid 0-100 range; dropped from progress dashboard aggregates.",
        })
        await prisma_model.update(where={"id": row_id}, data={flag_field: Json(existing)})
    except Exception as e:
        logger.warning(f"Failed to persist outlier flag ({flag_field}) on row {row_id}: {e}")


async def get_daily_streak_days(user_id: str) -> int:
    """The learner's Daily Challenge streak — read from the ONE source of truth.

    PDG-US-11 owns streaks (services/daily_challenge_service, kv-backed qualified_dates)
    and the Daily Challenge card / navbar icon render that number. This dashboard used to
    derive its own streak from a rolling 24-48h window over session rows, which answered a
    different question and showed the user a different number for the same word on the
    same screen. Reading the canonical value keeps the platform consistent.

    Best-effort: a streak lookup failure must never take down the whole dashboard.
    """
    try:
        from services import daily_challenge_service

        raw = await daily_challenge_service._get_streak_raw(user_id)
        _completed_today, alive_streak = daily_challenge_service._streak_view(
            raw, datetime.now(timezone.utc).date()
        )
        return alive_streak
    except Exception as e:
        logger.warning(f"Daily streak lookup failed: {e}")
        return 0


async def _fetch_completed_records_from_db(user_id: str) -> Tuple[List[Dict], int]:
    """
    Fetches completed session records across all module tables in DB,
    applying E-03 outlier score validation.
    """
    records: List[Dict] = []
    outliers_count = 0

    if not await _is_db_connected():
        return records, outliers_count

    # 1. BaselineAssessment
    try:
        baselines = await db.baselineassessment.find_many(
            where={"userId": user_id, "completedAt": {"not": None}}
        )
        for b in baselines:
            v_score, o1 = _validate_score(b.vocabularyScore)
            c_score, o2 = _validate_score(b.confidenceScore)
            f_score, o3 = _validate_score(b.fluencyScore)
            p_score, o4 = _validate_score(b.pronunciationScore)
            if any([o1, o2, o3, o4]):
                outliers_count += 1
                offending = [f for f, flagged in [
                    ("vocabulary_score", o1), ("confidence_score", o2),
                    ("fluency_score", o3), ("pronunciation_score", o4),
                ] if flagged]
                await _flag_outlier_row(db.baselineassessment, b.id, "outlierFlags", offending)

            dur = (b.completedAt - b.startedAt).total_seconds() if b.startedAt and b.completedAt else 60.0
            records.append({
                "source": "baseline",
                "completed_at": b.completedAt,
                "confidence_score": c_score,
                "fluency_score": f_score,
                "vocabulary_score": v_score,
                "pronunciation_score": p_score,
                "duration_seconds": max(0.0, dur),
            })
    except Exception as e:
        logger.warning(f"BaselineAssessment query failed: {e}")

    # 2. CoachingSession
    try:
        coaching = await db.coachingsession.find_many(
            where={"userId": user_id, "completedAt": {"not": None}}
        )
        for c in coaching:
            v_score, o1 = _validate_score(c.vocabularyScore)
            c_score, o2 = _validate_score(c.confidenceScore)
            f_score, o3 = _validate_score(c.fluencyScore)
            p_score, o4 = _validate_score(c.pronunciationScore)
            if any([o1, o2, o3, o4]):
                outliers_count += 1
                offending = [f for f, flagged in [
                    ("vocabulary_score", o1), ("confidence_score", o2),
                    ("fluency_score", o3), ("pronunciation_score", o4),
                ] if flagged]
                await _flag_outlier_row(db.coachingsession, c.id, "flags", offending)

            dur = (c.completedAt - c.createdAt).total_seconds() if c.createdAt and c.completedAt else 60.0
            records.append({
                "source": "coaching",
                "completed_at": c.completedAt,
                "confidence_score": c_score,
                "fluency_score": f_score,
                "vocabulary_score": v_score,
                "pronunciation_score": p_score,
                "duration_seconds": max(0.0, dur),
            })
    except Exception as e:
        logger.warning(f"CoachingSession query failed: {e}")

    # 3. ScenarioSession
    try:
        scenarios = await db.scenariosession.find_many(
            where={"userId": user_id, "completedAt": {"not": None}}
        )
        for s in scenarios:
            v_score, o1 = _validate_score(s.vocabularyScore)
            c_score, o2 = _validate_score(s.confidenceScore)
            if any([o1, o2]):
                outliers_count += 1
                offending = [f for f, flagged in [
                    ("vocabulary_score", o1), ("confidence_score", o2),
                ] if flagged]
                await _flag_outlier_row(db.scenariosession, s.id, "flags", offending)

            dur = (s.completedAt - s.createdAt).total_seconds() if s.createdAt and s.completedAt else 60.0
            records.append({
                "source": "scenario",
                "completed_at": s.completedAt,
                "confidence_score": c_score,
                "fluency_score": None,
                "vocabulary_score": v_score,
                "pronunciation_score": None,
                "duration_seconds": max(0.0, dur),
            })
    except Exception as e:
        logger.warning(f"ScenarioSession query failed: {e}")

    # 4. PublicSpeakingSession
    # Filtered on completedAt (like every other source above), not status=="completed":
    # a speech long enough to trigger the Q&A follow-up (PSC-US-12) moves to
    # status="qa_phase" immediately after scoring, without clearing completedAt or the
    # scorecard — filtering on status alone hid every such session from the dashboard
    # until the learner went back and answered the follow-up question, even though it
    # already had real scores.
    try:
        ps_sessions = await db.publicspeakingsession.find_many(
            where={"userId": user_id, "completedAt": {"not": None}}
        )
        for ps in ps_sessions:
            scorecard = ps.scorecard or {}
            raw_conf = scorecard.get("confidence", scorecard.get("overall_score"))
            raw_pacing = scorecard.get("pacing")
            raw_clarity = scorecard.get("voice_clarity")

            c_score, o1 = _validate_score(raw_conf)
            f_score, o2 = _validate_score(raw_pacing)
            p_score, o3 = _validate_score(raw_clarity)
            if any([o1, o2, o3]):
                outliers_count += 1
                offending = [f for f, flagged in [
                    ("confidence_score", o1), ("fluency_score", o2), ("pronunciation_score", o3),
                ] if flagged]
                await _flag_outlier_row(db.publicspeakingsession, ps.id, "outlierFlags", offending)

            dur = (ps.completedAt - ps.createdAt).total_seconds() if ps.createdAt and ps.completedAt else 60.0
            records.append({
                "source": "public_speaking",
                "completed_at": ps.completedAt or ps.createdAt,
                "confidence_score": c_score,
                "fluency_score": f_score,
                "vocabulary_score": None,
                "pronunciation_score": p_score,
                "duration_seconds": max(0.0, dur),
            })
    except Exception as e:
        logger.warning(f"PublicSpeakingSession query failed: {e}")

    # 5. AccentAssessment — pronunciation clarity only (no confidence/fluency/vocabulary
    # concept in this module). No outlierFlags column on this model, so a bad score is
    # dropped and counted but not persisted back onto the row like the sources above.
    try:
        accent_assessments = await db.accentassessment.find_many(
            where={"userId": user_id, "completedAt": {"not": None}}
        )
        for a in accent_assessments:
            p_score, outlier = _validate_score(a.pronunciationScore)
            if outlier:
                outliers_count += 1

            dur = (a.completedAt - a.createdAt).total_seconds() if a.createdAt and a.completedAt else 60.0
            records.append({
                "source": "accent",
                "completed_at": a.completedAt,
                "confidence_score": None,
                "fluency_score": None,
                "vocabulary_score": None,
                "pronunciation_score": p_score,
                "duration_seconds": max(0.0, dur),
            })
    except Exception as e:
        logger.warning(f"AccentAssessment query failed: {e}")

    # Sort records ascending by completed_at
    records.sort(key=lambda r: r["completed_at"])
    return records, outliers_count


async def _vocabulary_growth_detail(user_id: str) -> Dict:
    """Vocabulary growth from ScenarioSession, with the words and the PDG-US-14
    empty/zero-growth messaging the legacy overview payload renders.

    Single implementation — _fetch_vocab_growth_count is just the count view of this,
    so the "new words since last session" rule lives in exactly one place.
    """
    empty = {
        "new_words_count": 0,
        "new_words": [],
        "is_empty_state": True,
        "is_zero_growth": False,
        "message": _EMPTY_STATE_MESSAGE,
    }
    if not await _is_db_connected():
        return empty

    try:
        sessions = await db.scenariosession.find_many(
            where={"userId": user_id, "completedAt": {"not": None}}, order={"completedAt": "asc"}
        )
        if not sessions:
            return empty

        seen: set = set()
        for session in sessions[:-1]:
            seen.update(session.vocabUsed or [])

        latest_new_words = sorted(set(sessions[-1].vocabUsed or []) - seen)
        # E-03: cap so a scoring anomaly can't skew the chart.
        new_words_count = min(len(latest_new_words), MAX_DAILY_VOCAB_GROWTH)
        is_zero_growth = new_words_count == 0
        return {
            "new_words_count": new_words_count,
            "new_words": latest_new_words[:MAX_DAILY_VOCAB_GROWTH],
            "is_empty_state": False,
            "is_zero_growth": is_zero_growth,
            "message": _ZERO_GROWTH_MESSAGE if is_zero_growth else None,
        }
    except Exception as e:
        logger.warning(f"Vocab growth query failed: {e}")
        return empty


async def _fetch_vocab_growth_count(user_id: str) -> int:
    """Fetch vocabulary growth count from ScenarioSession."""
    return (await _vocabulary_growth_detail(user_id))["new_words_count"]


def _build_dashboard_payload(
    user_id: str,
    records: List[Dict],
    outliers_count: int,
    vocab_growth_count: int,
    sync_status: str = "synced",
    is_stale: bool = False,
    sync_message: Optional[str] = None,
    lifetime_practice_seconds: float = 0.0,
    daily_streak_days: int = 0,
) -> Dict:
    """Constructs the complete ProgressDashboardResponseSchema dict."""
    now_str = datetime.now(timezone.utc).isoformat()

    # E-02: Empty state for Day 1 users with 0 completed sessions
    if not records:
        primary_metric = PrimaryMetricSchema(
            name="Confidence Score",
            value=0.0,
            unit="pts",
            is_primary=True,
            description="Your primary overall confidence indicator across all learning modules.",
        )
        summary = ProgressDashboardMetricsSchema(
            confidence_score=primary_metric,
            fluency_score=None,
            vocabulary_score=None,
            pronunciation_score=None,
            total_practice_time_minutes=0.0,
            total_practice_time_hours=0.0,
            completed_sessions_count=0,
            vocabulary_growth_count=0,
            daily_streak_days=0,
        )
        return ProgressDashboardResponseSchema(
            user_id=user_id,
            generated_at=now_str,
            sync_status=sync_status,
            is_stale=is_stale,
            is_empty_state=True,
            empty_state_prompt=DAY1_MOTIVATIONAL_PROMPT,
            primary_metric=primary_metric,
            summary_metrics=summary,
            trend_lines=[],
            flagged_outliers_count=outliers_count,
            sync_message=sync_message or DAY1_MOTIVATIONAL_PROMPT,
        ).model_dump()

    # Calculate latest valid metrics
    def _latest(key: str) -> Optional[float]:
        for r in reversed(records):
            if r.get(key) is not None:
                return r[key]
        return None

    latest_conf = _latest("confidence_score") or 0.0
    latest_fluency = _latest("fluency_score")
    latest_vocab = _latest("vocabulary_score")
    latest_pron = _latest("pronunciation_score")

    # Total practice time comes from the SAME source of truth as the Practice Time
    # Milestones panel (practice_time_service): the ping-credited lifetime total on the
    # user, not a sum of per-session wall-clock spans. Summing spans counts idle/menu
    # time and drifts out of step with the Trophy Case; the ping total already excludes
    # idle, stale and concurrent-device pings. Per-session spans below are untouched —
    # they still drive the per-point trend chart.
    total_seconds = lifetime_practice_seconds
    total_minutes = round(total_seconds / 60.0, 1)
    total_hours = round(total_seconds / 3600.0, 2)
    streak_days = daily_streak_days

    primary_metric = PrimaryMetricSchema(
        name="Confidence Score",
        value=latest_conf,
        unit="pts",
        is_primary=True,
        description="Your primary overall confidence indicator across all learning modules.",
    )

    summary = ProgressDashboardMetricsSchema(
        confidence_score=primary_metric,
        fluency_score=latest_fluency,
        vocabulary_score=latest_vocab,
        pronunciation_score=latest_pron,
        total_practice_time_minutes=total_minutes,
        total_practice_time_hours=total_hours,
        completed_sessions_count=len(records),
        vocabulary_growth_count=vocab_growth_count,
        daily_streak_days=streak_days,
    )

    # Build trend lines for visual charts
    trend_lines: List[TrendPointSchema] = []
    for r in records:
        d_str = r["completed_at"].isoformat() if hasattr(r["completed_at"], "isoformat") else str(r["completed_at"])
        p_min = round(r.get("duration_seconds", 0.0) / 60.0, 1)
        trend_lines.append(
            TrendPointSchema(
                date=d_str,
                confidence_score=r.get("confidence_score"),
                fluency_score=r.get("fluency_score"),
                vocabulary_score=r.get("vocabulary_score"),
                pronunciation_score=r.get("pronunciation_score"),
                practice_time_minutes=p_min,
            )
        )

    # Cap trend lines payload to recent 30 points
    trend_lines = trend_lines[-30:]

    return ProgressDashboardResponseSchema(
        user_id=user_id,
        generated_at=now_str,
        sync_status=sync_status,
        is_stale=is_stale,
        is_empty_state=False,
        empty_state_prompt=None,
        primary_metric=primary_metric,
        summary_metrics=summary,
        trend_lines=trend_lines,
        flagged_outliers_count=outliers_count,
        sync_message=sync_message,
    ).model_dump()


async def get_progress_dashboard(user_id: str = Depends(require_auth)) -> Dict:
    """
    Main API Handler for GET /api/progress-dashboard/progress.
    Fetches real-time metrics across all session models.
    Handles E-01 DB failure with last-known-good snapshot fallback.
    """
    try:
        # Check KV store for seeded / simulated session records during test runs
        kv_records = await kv_store.store.get("test_dashboard_records", user_id)
        if kv_records and isinstance(kv_records, list):
            db_records = kv_records
            outliers_count = 0
            # Apply E-03 validation to test records
            clean_records = []
            for r in db_records:
                c_score, o1 = _validate_score(r.get("confidence_score"))
                f_score, o2 = _validate_score(r.get("fluency_score"))
                v_score, o3 = _validate_score(r.get("vocabulary_score"))
                p_score, o4 = _validate_score(r.get("pronunciation_score"))
                if any([o1, o2, o3, o4]):
                    outliers_count += 1
                r_clean = dict(r)
                r_clean["confidence_score"] = c_score
                r_clean["fluency_score"] = f_score
                r_clean["vocabulary_score"] = v_score
                r_clean["pronunciation_score"] = p_score
                clean_records.append(r_clean)
            db_records = clean_records
        else:
            db_records, outliers_count = await _fetch_completed_records_from_db(user_id)

        vocab_growth = await _fetch_vocab_growth_count(user_id)
        # Single source of truth for practice time — see _build_dashboard_payload.
        dashboard_user = await db.user.find_unique(where={"id": user_id})
        payload = _build_dashboard_payload(
            user_id,
            db_records,
            outliers_count,
            vocab_growth,
            lifetime_practice_seconds=(dashboard_user.lifetimePracticeSeconds if dashboard_user else 0.0),
            daily_streak_days=await get_daily_streak_days(user_id),
        )

        # E-01: Save last-known-good snapshot to KV store. create() fails with a
        # unique-constraint violation once a snapshot row already exists for this
        # user, so update the existing row instead of always creating.
        existing_snapshot = await kv_store.store.get(DASHBOARD_SNAPSHOT_NS, user_id)
        if existing_snapshot is None:
            await kv_store.store.create(DASHBOARD_SNAPSHOT_NS, user_id, payload)
        else:
            await kv_store.store.update(DASHBOARD_SNAPSHOT_NS, user_id, payload)
        return payload

    except Exception as exc:
        logger.error(f"Error building progress dashboard for user {user_id}: {exc}")
        # E-01 Fallback: fetch last known good snapshot from KV store
        snapshot = await kv_store.store.get(DASHBOARD_SNAPSHOT_NS, user_id)
        if snapshot and isinstance(snapshot, dict):
            snapshot["sync_status"] = "stale"
            snapshot["is_stale"] = True
            snapshot["sync_message"] = SYNC_STALE_MESSAGE
            return snapshot

        # If no snapshot exists, return zero-state payload with stale flag
        return _build_dashboard_payload(
            user_id,
            records=[],
            outliers_count=0,
            vocab_growth_count=0,
            sync_status="stale",
            is_stale=True,
            sync_message=SYNC_STALE_MESSAGE,
        )


async def get_overview(user_id: str = Depends(require_auth)):
    """Backwards-compatible endpoint for existing UI / tests.

    Returns the flat legacy shape the Vocabulary Growth panel reads
    (has_data / metrics / vocabulary_growth / vocabulary_history). The richer
    time-series payload lives on /progress and /track via get_progress_dashboard —
    this deliberately does NOT delegate to it, because that response has a different
    schema and would break the existing panel.
    """
    from services.gating_service import GatedFeature, check_feature_access

    access = await check_feature_access(user_id, GatedFeature.PROGRESS_DASHBOARD.value)
    if not access["accessible"]:
        return JSONResponse(status_code=403, content={"error": access["reason"], "gating": access})

    records, _outliers = await _fetch_completed_records_from_db(user_id)
    records.sort(key=lambda r: r["completed_at"])
    growth = await _vocabulary_growth_detail(user_id)

    # Same single source of truth for practice time as the Milestones panel.
    user = await db.user.find_unique(where={"id": user_id})
    practice_time_minutes = round((user.lifetimePracticeSeconds if user else 0.0) / 60, 1)

    def _latest(key: str) -> Optional[float]:
        for record in reversed(records):
            value = record.get(key)
            if value is not None:
                return round(value, 2)
        return None

    vocabulary_history = [
        {"date": r["completed_at"].isoformat(), "vocabulary_score": round(r["vocabulary_score"], 2)}
        for r in records
        if r.get("vocabulary_score") is not None
    ][-20:]  # cap chart payload to the most recent 20 points

    return {
        "has_data": bool(records),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "practice_time_minutes": practice_time_minutes,
            "confidence_score": _latest("confidence_score"),
            "fluency_score": _latest("fluency_score"),
            "vocabulary_score": _latest("vocabulary_score"),
        },
        "vocabulary_growth": growth,
        "vocabulary_history": vocabulary_history,
    }
