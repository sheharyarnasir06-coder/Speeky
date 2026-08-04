"""
Content Management — Template Performance Dashboard (CM-US-09 / US-193).

Aggregates learner outcomes and engagement per published template.

Two acceptance criteria shape the design:

* "Performance metrics updated continuously" — metrics are computed on read from
  `scenario_sessions`, never from a cached counter that could drift out of sync
  with the sessions themselves.
* "Historical trends preserved" — a read-time aggregate only ever shows *now*, so
  `capture_snapshot` persists the point-in-time bundle into
  `template_performance_snapshots`. The trend line then survives session pruning.

Every metric is nullable. A metric with no data returns None (rendered as "no
data" by the UI) rather than 0, because 0% completion and "nobody has tried it
yet" are completely different facts and must not look alike.

Performance: one `find_many` per scenario, aggregated in Python. Deliberately not
one query per metric — that would be a 7x N+1 against the same rows.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from prisma import Json

from lib.prisma_client import db
from lib.scoring import as_utc

logger = logging.getLogger(__name__)

# Below this many sessions the numbers are noise, so they are returned with
# `insufficient_data` set and the UI labels them provisional rather than hiding
# them (CM-US-09 exception: "Insufficient learner data").
MIN_SAMPLE_FOR_CONFIDENCE = 5

# A template created within this window with no/low usage is "newly published"
# rather than "underperforming" — a distinct exception case in the spec.
NEW_TEMPLATE_GRACE_HOURS = 72

# An in_progress session older than this is counted as abandoned rather than
# live. Matches the practical reality that nobody resumes a day-old roleplay.
STALE_IN_PROGRESS_HOURS = 24

# Confidence improvement compares the first and last thirds of the session
# history; a straight first-vs-last comparison is far too noisy on small samples.
_TREND_MIN_SESSIONS = 6


def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def _pct(numerator: int, denominator: int) -> Optional[float]:
    return round(100 * numerator / denominator, 1) if denominator else None


def scenario_key_for(scenario_id: str) -> str:
    """Sessions reference custom scenarios by this composite key, not by FK."""
    return f"custom:{scenario_id}"


def compute_metrics(sessions: List, scenario=None) -> Dict:
    """Pure aggregation over already-fetched rows — no DB access, so it is
    directly unit-testable and callable per-scenario from a batch fetch without
    re-querying."""
    now = datetime.now(timezone.utc)
    total = len(sessions)

    if total == 0:
        newly_published = bool(
            scenario is not None
            and (now - as_utc(scenario.createdAt)) < timedelta(hours=NEW_TEMPLATE_GRACE_HOURS)
        )
        return {
            "usage_count": 0,
            "completion_rate": None,
            "average_learner_score": None,
            "confidence_improvement": None,
            "vocabulary_success_rate": None,
            "session_abandonment": None,
            "learner_satisfaction": None,
            "sample_size": 0,
            "insufficient_data": True,
            "newly_published": newly_published,
            "no_analytics": True,
        }

    completed = [s for s in sessions if s.status == "completed"]
    ended_early = [s for s in sessions if s.status == "ended_early"]
    stale = [
        s for s in sessions
        if s.status == "in_progress"
        and (now - as_utc(s.createdAt)) > timedelta(hours=STALE_IN_PROGRESS_HOURS)
    ]

    # Only scored sessions contribute to score means — an in_progress row has no
    # scores yet and averaging its nulls as zeros would drag the mean down.
    scored = [s for s in sessions if s.confidenceScore is not None]
    confidence_values = [float(s.confidenceScore) for s in scored]

    vocab_rates: List[float] = []
    for s in sessions:
        target = list(s.targetVocab or [])
        if not target:
            continue
        used = {w.lower() for w in (s.vocabUsed or [])}
        vocab_rates.append(100 * sum(1 for w in target if w.lower() in used) / len(target))

    ratings = [float(s.satisfactionRating) for s in sessions if s.satisfactionRating is not None]

    return {
        "usage_count": total,
        "completion_rate": _pct(len(completed), total),
        "average_learner_score": _mean(confidence_values),
        "confidence_improvement": _confidence_improvement(scored),
        "vocabulary_success_rate": _mean(vocab_rates),
        "session_abandonment": _pct(len(ended_early) + len(stale), total),
        # None (not 0) when nobody rated — "unrated" must not read as "rated badly".
        "learner_satisfaction": _mean(ratings),
        "satisfaction_responses": len(ratings),
        "sample_size": total,
        "insufficient_data": total < MIN_SAMPLE_FOR_CONFIDENCE,
        "newly_published": bool(
            scenario is not None
            and (now - as_utc(scenario.createdAt)) < timedelta(hours=NEW_TEMPLATE_GRACE_HOURS)
        ),
        "no_analytics": False,
    }


def _confidence_improvement(scored: List) -> Optional[float]:
    """Mean confidence of the most recent third minus the earliest third.
    Positive means learners are doing better on this template over time."""
    if len(scored) < _TREND_MIN_SESSIONS:
        return None
    ordered = sorted(scored, key=lambda s: as_utc(s.createdAt))
    third = max(1, len(ordered) // 3)
    first = [float(s.confidenceScore) for s in ordered[:third]]
    last = [float(s.confidenceScore) for s in ordered[-third:]]
    return round((sum(last) / len(last)) - (sum(first) / len(first)), 2)


async def metrics_for_scenario(scenario_id: str) -> Dict:
    scenario = await db.customscenario.find_unique(where={"id": scenario_id})
    sessions = await db.scenariosession.find_many(
        where={"scenarioKey": scenario_key_for(scenario_id)}
    )
    metrics = compute_metrics(sessions, scenario)
    # CM-US-09 exception: archived templates still report history, but the UI
    # must be able to say the numbers are frozen rather than live.
    metrics["archived"] = bool(scenario and scenario.status == "ARCHIVED")
    return metrics


async def metrics_for_all() -> List[Dict]:
    """Dashboard list view. Two queries total regardless of template count — the
    naive shape here is one session query per scenario (an N+1 that grew with the
    catalogue), so sessions are fetched once and bucketed in memory."""
    scenarios = await db.customscenario.find_many(order={"createdAt": "desc"})
    if not scenarios:
        return []

    keys = [scenario_key_for(s.id) for s in scenarios]
    sessions = await db.scenariosession.find_many(where={"scenarioKey": {"in": keys}})

    buckets: Dict[str, List] = {key: [] for key in keys}
    for session in sessions:
        buckets.setdefault(session.scenarioKey, []).append(session)

    rows = []
    for scenario in scenarios:
        metrics = compute_metrics(buckets.get(scenario_key_for(scenario.id), []), scenario)
        metrics["archived"] = scenario.status == "ARCHIVED"
        rows.append({
            "scenario_id": scenario.id,
            "title": scenario.title,
            "category": scenario.category,
            "status": scenario.status,
            "version": scenario.version,
            "created_at": scenario.createdAt.isoformat(),
            "metrics": metrics,
        })
    return rows


async def capture_snapshot(scenario_id: str, metrics: Optional[Dict] = None) -> Dict:
    """Persist the current bundle so the trend survives session pruning.
    Idempotent-ish by design: callers snapshot on meaningful events (a publish, an
    admin opening the dashboard), not on a timer, since this repo has no scheduler."""
    if metrics is None:
        metrics = await metrics_for_scenario(scenario_id)
    row = await db.templateperformancesnapshot.create(
        data={
            "scenarioId": scenario_id,
            "metrics": Json(metrics),
            "sampleSize": int(metrics.get("sample_size") or 0),
        }
    )
    return {"id": row.id, "captured_at": row.capturedAt.isoformat(), "metrics": metrics}


async def trend_for_scenario(scenario_id: str, limit: int = 30) -> List[Dict]:
    rows = await db.templateperformancesnapshot.find_many(
        where={"scenarioId": scenario_id}, order={"capturedAt": "desc"}, take=limit
    )
    # Oldest-first for charting; the query is newest-first only to make `take`
    # select the most recent N.
    return [
        {"captured_at": r.capturedAt.isoformat(), "sample_size": r.sampleSize, "metrics": r.metrics}
        for r in reversed(rows)
    ]
