"""
Content Management — Content Drift Detection (CM-US-12 / US-196).

Detects when a published scenario stops performing the way it used to, by
comparing a RECENT window of learner sessions against an earlier BASELINE window
of the same scenario. Five monitored signals, straight from the spec:

    learner completion · AI response consistency · vocabulary achievement
    confidence improvements · user feedback

Drift is deliberately measured against the template's own past, not against a
global average — a hard scenario that has always had a 40% completion rate is
working as designed, and flagging it would train admins to ignore alerts.

The four spec exception cases are handled as suppression rules rather than as
error paths, because each describes a case where the *numbers* moved but the
*content* did not actually break:

  * Low sample size    -> below MIN_WINDOW_SESSIONS per window, no alert at all.
  * Temporary anomaly  -> a single degraded signal at modest magnitude is INFO,
                          not an alert; real drift shows up on multiple signals.
  * Seasonal variation -> deltas within SEASONAL_TOLERANCE are treated as normal
                          fluctuation rather than degradation.
  * AI model update    -> when EVERY scenario degrades on the same signal at the
                          same time, the cause is platform-wide (a model swap),
                          not this template; see `detect_all`.

There is no scheduler in this repo, so detection runs opportunistically when an
admin opens the dashboard — the same pattern already used by
scenario_service._purge_idle_archives.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from prisma import Json

from lib.prisma_client import db
from lib.scoring import as_utc
from services import template_performance_service as perf

logger = logging.getLogger(__name__)

# Each window needs at least this many sessions before any comparison is
# meaningful (CM-US-12 exception: "Low sample size").
MIN_WINDOW_SESSIONS = 5

# Deltas smaller than this are normal fluctuation, not drift (CM-US-12
# exception: "Seasonal variation"). Percentage points for rate signals.
SEASONAL_TOLERANCE = 8.0

# A single degraded signal below this magnitude is a temporary anomaly, not an
# alert (CM-US-12 exception: "Temporary anomaly").
ANOMALY_MAGNITUDE = 15.0

# Two or more degraded signals, or one severe one, constitutes real drift.
CRITICAL_SIGNAL_COUNT = 3

# When at least this fraction of all scenarios degrade on the same signal in the
# same run, the cause is treated as platform-wide (CM-US-12 exception: "AI model
# update impact") and per-template alerts for that signal are suppressed.
PLATFORM_WIDE_FRACTION = 0.6

# The comparison windows. Recent = last 14 days, baseline = the 28 days before.
RECENT_WINDOW_DAYS = 14
BASELINE_WINDOW_DAYS = 42

# Signals where a LOWER number is worse. `session_abandonment` is inverted — a
# rise there is degradation — and is handled explicitly below.
_LOWER_IS_WORSE = (
    ("completion_rate", "Learner completion"),
    ("vocabulary_success_rate", "Vocabulary achievement"),
    ("average_learner_score", "AI response consistency"),
    ("confidence_improvement", "Confidence improvement"),
    ("learner_satisfaction", "User feedback"),
)


def _delta(recent: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if recent is None or baseline is None:
        return None
    return round(recent - baseline, 2)


def compare_windows(baseline: Dict, recent: Dict) -> Dict:
    """Pure comparison of two metric bundles — no DB, so it is directly testable.

    Returns every signal with its baseline/recent/delta plus whether it counts as
    degraded, and a severity that already accounts for the anomaly and seasonal
    suppression rules.
    """
    signals: Dict[str, Dict] = {}

    for key, label in _LOWER_IS_WORSE:
        delta = _delta(recent.get(key), baseline.get(key))
        # learner_satisfaction is a 1-5 scale, not a percentage — scale its delta
        # to comparable magnitude so one tolerance constant works for all signals.
        magnitude = abs(delta) * 20 if (delta is not None and key == "learner_satisfaction") else abs(delta or 0)
        degraded = delta is not None and delta < 0 and magnitude > SEASONAL_TOLERANCE
        signals[key] = {
            "label": label,
            "baseline": baseline.get(key),
            "recent": recent.get(key),
            "delta": delta,
            "magnitude": round(magnitude, 2),
            "degraded": degraded,
            "no_data": delta is None,
        }

    # Abandonment is inverted: going UP is the bad direction.
    abandon_delta = _delta(recent.get("session_abandonment"), baseline.get("session_abandonment"))
    signals["session_abandonment"] = {
        "label": "Session abandonment",
        "baseline": baseline.get("session_abandonment"),
        "recent": recent.get("session_abandonment"),
        "delta": abandon_delta,
        "magnitude": round(abs(abandon_delta or 0), 2),
        "degraded": abandon_delta is not None and abandon_delta > SEASONAL_TOLERANCE,
        "no_data": abandon_delta is None,
    }

    degraded = [key for key, signal in signals.items() if signal["degraded"]]
    worst = max((signals[k]["magnitude"] for k in degraded), default=0.0)

    if not degraded:
        severity = None
    elif len(degraded) == 1 and worst < ANOMALY_MAGNITUDE:
        # CM-US-12: one modest wobble on one signal is an anomaly, not drift.
        severity = "INFO"
    elif len(degraded) >= CRITICAL_SIGNAL_COUNT or worst >= 30:
        severity = "CRITICAL"
    else:
        severity = "WARNING"

    return {"signals": signals, "degraded": degraded, "severity": severity, "worst_magnitude": worst}


def _split_windows(sessions: List) -> Dict[str, List]:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=RECENT_WINDOW_DAYS)
    baseline_start = now - timedelta(days=BASELINE_WINDOW_DAYS)
    recent, baseline = [], []
    for session in sessions:
        created = as_utc(session.createdAt)
        if created >= recent_start:
            recent.append(session)
        elif created >= baseline_start:
            baseline.append(session)
    return {"recent": recent, "baseline": baseline}


def _summarise(title: str, comparison: Dict) -> str:
    parts = []
    for key in comparison["degraded"]:
        signal = comparison["signals"][key]
        direction = "up" if key == "session_abandonment" else "down"
        parts.append(f"{signal['label']} {direction} {abs(signal['delta'])}")
    return f'"{title}" is drifting — ' + "; ".join(parts) + " versus its earlier baseline."


async def analyse_scenario(scenario_id: str) -> Dict:
    """Compute drift for one scenario without persisting anything."""
    scenario = await db.customscenario.find_unique(where={"id": scenario_id})
    if not scenario:
        return {"error": "not_found"}
    sessions = await db.scenariosession.find_many(
        where={"scenarioKey": perf.scenario_key_for(scenario_id)}
    )
    return _analyse_from_sessions(scenario, sessions)


def _analyse_from_sessions(scenario, sessions: List) -> Dict:
    windows = _split_windows(sessions)
    recent_n, baseline_n = len(windows["recent"]), len(windows["baseline"])

    if recent_n < MIN_WINDOW_SESSIONS or baseline_n < MIN_WINDOW_SESSIONS:
        # CM-US-12 exception: low sample size — explicitly reported, never alerted.
        return {
            "scenario_id": scenario.id,
            "title": scenario.title,
            "status": "insufficient_data",
            "recent_sessions": recent_n,
            "baseline_sessions": baseline_n,
            "required_per_window": MIN_WINDOW_SESSIONS,
            "severity": None,
            "signals": {},
            "degraded": [],
        }

    baseline_metrics = perf.compute_metrics(windows["baseline"], scenario)
    recent_metrics = perf.compute_metrics(windows["recent"], scenario)
    comparison = compare_windows(baseline_metrics, recent_metrics)

    return {
        "scenario_id": scenario.id,
        "title": scenario.title,
        "status": "analysed",
        "recent_sessions": recent_n,
        "baseline_sessions": baseline_n,
        "baseline_metrics": baseline_metrics,
        "recent_metrics": recent_metrics,
        "severity": comparison["severity"],
        "signals": comparison["signals"],
        "degraded": comparison["degraded"],
        "summary": _summarise(scenario.title, comparison) if comparison["severity"] else "",
    }


def suppress_platform_wide(analyses: List[Dict]) -> List[str]:
    """CM-US-12 exception: "AI model update impact".

    If the same signal degraded across most of the catalogue in one run, the
    cause is the platform (a model swap, an infra change), not any individual
    template. Those signals are returned so callers can exclude them — alerting
    on every template at once would be pure noise at exactly the moment admins
    need signal.
    """
    analysed = [a for a in analyses if a.get("status") == "analysed"]
    if len(analysed) < 3:
        # Too few templates for "most of them" to mean anything.
        return []
    suppressed = []
    for key, _label in (*_LOWER_IS_WORSE, ("session_abandonment", "Session abandonment")):
        degraded_count = sum(1 for a in analysed if key in a.get("degraded", []))
        if degraded_count / len(analysed) >= PLATFORM_WIDE_FRACTION:
            suppressed.append(key)
    return suppressed


async def detect_all(persist: bool = True) -> Dict:
    """Run drift detection across every active template.

    Two queries total (scenarios, then all their sessions) — not one query per
    template.
    """
    scenarios = await db.customscenario.find_many(where={"status": "ACTIVE"})
    if not scenarios:
        return {"analyses": [], "alerts_created": 0, "platform_wide_signals": []}

    keys = [perf.scenario_key_for(s.id) for s in scenarios]
    sessions = await db.scenariosession.find_many(where={"scenarioKey": {"in": keys}})
    buckets: Dict[str, List] = {key: [] for key in keys}
    for session in sessions:
        buckets.setdefault(session.scenarioKey, []).append(session)

    analyses = [
        _analyse_from_sessions(scenario, buckets.get(perf.scenario_key_for(scenario.id), []))
        for scenario in scenarios
    ]

    platform_wide = suppress_platform_wide(analyses)
    alerts_created = 0

    for analysis in analyses:
        if analysis.get("status") != "analysed" or not analysis.get("severity"):
            continue
        # Drop platform-wide signals, then re-check whether anything is left.
        remaining = [key for key in analysis["degraded"] if key not in platform_wide]
        if not remaining:
            analysis["severity"] = None
            analysis["suppressed_reason"] = "platform_wide"
            continue
        if analysis["severity"] == "INFO":
            # Anomaly-level: surfaced in the response, never persisted as an alert.
            continue
        if persist and await _create_alert_if_new(analysis, remaining):
            alerts_created += 1

    return {
        "analyses": analyses,
        "alerts_created": alerts_created,
        "platform_wide_signals": platform_wide,
    }


async def _create_alert_if_new(analysis: Dict, degraded: List[str]) -> bool:
    """Suppress duplicates: if an OPEN alert already covers the same signal set,
    don't create a second one — an admin who has already been told does not need
    telling again on every dashboard load."""
    existing = await db.contentdriftalert.find_first(
        where={"scenarioId": analysis["scenario_id"], "status": "OPEN"}
    )
    if existing:
        previous = sorted((existing.signals or {}).get("degraded", []))
        if previous == sorted(degraded):
            return False
    await db.contentdriftalert.create(
        data={
            "scenarioId": analysis["scenario_id"],
            "severity": analysis["severity"],
            "summary": analysis["summary"],
            "signals": Json({"degraded": degraded, "detail": analysis["signals"]}),
        }
    )
    return True


async def list_alerts(status: Optional[str] = None) -> List[Dict]:
    where = {"status": status} if status else {}
    rows = await db.contentdriftalert.find_many(where=where, order={"detectedAt": "desc"}, take=100)
    return [
        {
            "id": r.id,
            "scenario_id": r.scenarioId,
            "severity": r.severity,
            "summary": r.summary,
            "signals": r.signals,
            "status": r.status,
            "detected_at": r.detectedAt.isoformat(),
            "acknowledged_at": r.acknowledgedAt.isoformat() if r.acknowledgedAt else None,
        }
        for r in rows
    ]


async def acknowledge_alert(alert_id: str) -> Optional[Dict]:
    row = await db.contentdriftalert.find_unique(where={"id": alert_id})
    if not row:
        return None
    updated = await db.contentdriftalert.update(
        where={"id": alert_id},
        data={"status": "ACKNOWLEDGED", "acknowledgedAt": datetime.now(timezone.utc)},
    )
    return {
        "id": updated.id,
        "status": updated.status,
        "acknowledged_at": updated.acknowledgedAt.isoformat() if updated.acknowledgedAt else None,
    }
