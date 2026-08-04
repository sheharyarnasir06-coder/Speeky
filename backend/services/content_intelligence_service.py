"""
Content Management — HTTP handlers for the Sprint 3 content-intelligence suite.

    US-192 Vocabulary Coverage Score        -> vocab_coverage_service
    US-193 Template Performance Dashboard   -> template_performance_service
    US-195 Prompt Explainability Report     -> prompt_explainability_service
    US-196 Content Drift Detection          -> content_drift_service
    US-198 Deployment Confidence Monitoring -> deployment_confidence_service

This module is deliberately thin: it owns request/response shaping, persistence
of computed results, and authorization, while every scoring decision lives in the
pure service it delegates to. That split keeps the scoring logic unit-testable
without HTTP, and keeps this file's behaviour obvious at a glance.

Handler-functions-as-routes matches the existing convention in this codebase
(see scenario_service.admin_*), so routing stays consistent across the project.

US-197 (Automated Content Improvement Recommendations) is intentionally NOT
implemented. The seam for it is `recommendations` on the vocab-coverage and
explainability payloads plus the drift analyses — a future US-197 service can
consume those without any refactor here.
"""

import logging
from datetime import datetime, timezone
from fastapi import Depends
from fastapi.responses import JSONResponse
from prisma import Json

from lib.prisma_client import db
from middlewares.auth_middleware import require_admin, require_auth
from schemas.content_intelligence_schemas import SatisfactionRatingSchema
from services import (
    content_drift_service,
    deployment_confidence_service,
    prompt_explainability_service,
    template_performance_service,
    vocab_coverage_service,
)

logger = logging.getLogger(__name__)

_NOT_FOUND = JSONResponse(status_code=404, content={"error": "Custom scenario not found"})


async def _load(scenario_id: str):
    return await db.customscenario.find_unique(where={"id": scenario_id})


def _shape(row) -> dict:
    """The snake_case scenario dict the scoring services expect."""
    return {
        "title": row.title,
        "category": row.category,
        "persona": row.persona,
        "intent": row.intent,
        "system_prompt": row.systemPrompt,
        "opening_line": row.openingLine,
        "target_vocab": row.targetVocab,
        "goal_type": row.goalType,
        "difficulty": row.difficulty,
        "sandbox_tested": row.sandboxTested,
    }


# ── US-192: Vocabulary Coverage Score ────────────────────────────────────────
async def admin_score_vocab_coverage(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND

    result = await vocab_coverage_service.score_coverage(_shape(row))
    await db.customscenario.update(
        where={"id": scenario_id},
        data={
            "vocabCoverageScore": result["coverage_score"],
            "vocabCoverageFeedback": Json({
                "breakdown": result["breakdown"],
                "flags": result["flags"],
                "recommendations": result["recommendations"],
                "suggested_additions": result["suggested_additions"],
                "redundant_words": result["redundant_words"],
                "source": result["_source"],
                "note": result.get("_note", ""),
            }),
            "vocabCoverageAt": datetime.now(timezone.utc),
        },
    )
    return {"scenario_id": scenario_id, **result}


async def admin_get_vocab_coverage(scenario_id: str, user_id: str = Depends(require_admin)):
    """Cached read so opening the panel is not an LLM call every time."""
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND
    return {
        "scenario_id": scenario_id,
        "coverage_score": row.vocabCoverageScore,
        "feedback": row.vocabCoverageFeedback,
        "scored_at": row.vocabCoverageAt.isoformat() if row.vocabCoverageAt else None,
        "stale": row.vocabCoverageAt is None,
    }


# ── US-195: Prompt Explainability Report ─────────────────────────────────────
async def admin_explain_prompt(scenario_id: str, user_id: str = Depends(require_admin)):
    """CM-US-11 happy path: admin selects "View Analysis"."""
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND

    quality_breakdown = ((row.qualityFeedback or {}).get("breakdown")) or {}
    report = await prompt_explainability_service.explain(
        _shape(row), row.qualityScore, quality_breakdown, row.confidenceScore
    )
    await db.customscenario.update(
        where={"id": scenario_id},
        data={"explainabilityReport": Json(report), "explainabilityAt": datetime.now(timezone.utc)},
    )
    return {"scenario_id": scenario_id, **report}


async def admin_get_explanation(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND
    return {
        "scenario_id": scenario_id,
        "report": row.explainabilityReport,
        "generated_at": row.explainabilityAt.isoformat() if row.explainabilityAt else None,
        "stale": row.explainabilityAt is None,
    }


# ── US-193: Template Performance Dashboard ───────────────────────────────────
async def admin_performance_overview(user_id: str = Depends(require_admin)):
    rows = await template_performance_service.metrics_for_all()
    return {"templates": rows, "count": len(rows)}


async def admin_performance_detail(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND
    metrics = await template_performance_service.metrics_for_scenario(scenario_id)
    trend = await template_performance_service.trend_for_scenario(scenario_id)
    return {
        "scenario_id": scenario_id,
        "title": row.title,
        "status": row.status,
        "metrics": metrics,
        "trend": trend,
    }


async def admin_capture_performance_snapshot(scenario_id: str, user_id: str = Depends(require_admin)):
    """CM-US-09 acceptance: "Historical trends preserved."."""
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND
    return await template_performance_service.capture_snapshot(scenario_id)


# ── US-196: Content Drift Detection ──────────────────────────────────────────
async def admin_drift_overview(user_id: str = Depends(require_admin)):
    """Runs detection opportunistically (no scheduler exists in this repo) and
    returns both the analyses and any alerts already on record."""
    result = await content_drift_service.detect_all(persist=True)
    alerts = await content_drift_service.list_alerts()
    return {
        "analyses": result["analyses"],
        "alerts": alerts,
        "alerts_created": result["alerts_created"],
        "platform_wide_signals": result["platform_wide_signals"],
    }


async def admin_drift_detail(scenario_id: str, user_id: str = Depends(require_admin)):
    analysis = await content_drift_service.analyse_scenario(scenario_id)
    if analysis.get("error") == "not_found":
        return _NOT_FOUND
    return analysis


async def admin_acknowledge_drift_alert(alert_id: str, user_id: str = Depends(require_admin)):
    result = await content_drift_service.acknowledge_alert(alert_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "Drift alert not found"})
    return result


# ── US-198: Deployment Confidence Monitoring ─────────────────────────────────
async def admin_deployment_confidence(scenario_id: str, user_id: str = Depends(require_admin)):
    result = await deployment_confidence_service.evaluate(scenario_id)
    if result is None:
        return _NOT_FOUND
    return result


async def admin_deployment_history(scenario_id: str, user_id: str = Depends(require_admin)):
    row = await _load(scenario_id)
    if not row:
        return _NOT_FOUND
    return {
        "scenario_id": scenario_id,
        "current_version": row.version,
        "deployments": await deployment_confidence_service.deployment_history(scenario_id),
    }


# ── US-193 / US-196 input: learner satisfaction ──────────────────────────────
async def rate_session(session_id: str, payload: SatisfactionRatingSchema,
                       user_id: str = Depends(require_auth)):
    """Feeds "Learner satisfaction" (CM-US-09) and the "user feedback" drift
    signal (CM-US-12). Deliberately owner-scoped, not admin: a learner rates only
    their own session, and rating is always optional."""
    session = await db.scenariosession.find_unique(where={"id": session_id})
    if not session:
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    if session.userId != user_id:
        # 404 rather than 403 so this cannot be used to probe which session ids exist.
        return JSONResponse(status_code=404, content={"error": "Session not found"})

    updated = await db.scenariosession.update(
        where={"id": session_id}, data={"satisfactionRating": payload.rating}
    )
    return {"session_id": session_id, "satisfaction_rating": updated.satisfactionRating}
