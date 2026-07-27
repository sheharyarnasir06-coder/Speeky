"""
Accent Assessment — US-82 (ACC-US-03 Target Accent Selection),
US-83 (ACC-US-04 Score Dispute), US-84 (ACC-US-05 Profile Staleness).

Thin controller layer over lib/accent_assessment/, which already implements
all three stories' rules against one shared substrate
(AccentProfilePipelineService / AccentProfile / AccentAssessmentResult in
profile_pipeline.py). Combined into one router+service, matching how the
lib layer itself is organised as a single subpackage sharing that pipeline,
rather than three near-duplicate router/service pairs each re-reading the
same AccentProfile.

Where the real data comes from:
This backend never stores raw audio (see conversation_service.py's module
docstring), so there is no dedicated "read this sentence aloud, get an
accent baseline" recording flow yet. Rather than fabricate scores, baselines
and drills here are derived from a user's own completed AI Conversation
Practice sessions' real fluency/vocabulary/pronunciation scores
(session_scorer.py, already computed at conversation-end):
  * record_conversation_drill() is called (best-effort) by
    conversation_service._end_session() every time a session ends — this
    keeps AccentProfile.drills_history populated with genuinely-scored data
    and, on a user's very first conversation, establishes their initial
    timestamped baseline so staleness tracking has a real starting point.
  * The explicit "retake a quick baseline" action (POST /rebaseline) reuses
    a specific completed session's real scores rather than accepting
    client-supplied numbers, which would otherwise let a client fabricate
    its own score.

Honest limitation: because conversation sessions never have real audio
attached (audio_clip_id is set to the session_id purely for
correlation/dispute-linking, is_audio_available is always False), every
dispute against a conversation-derived assessment will hit score_dispute.py's
E-03 "audio no longer available" path today. E-01 (high-volume auto-flag)
and E-02 (daily rate limit) are unaffected by that and fully exercise real
code. See the final summary for how to get the E-03-free happy path once a
real audio-backed assessment type exists.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends
from fastapi.responses import JSONResponse

from lib.accent_assessment.accent_profile_staleness import AccentProfileStalenessService
from lib.accent_assessment.profile_pipeline import (
    AccentAssessmentResult,
    AccentProfile,
    AccentProfilePipelineService,
    ScoredMetric,
    calculate_overall_accent_score,
)
from lib.accent_assessment.score_dispute import ScoreDisputeService
from lib.accent_assessment.target_accent_selection import TargetAccentSelectionService
from middlewares.auth_middleware import require_auth
from schemas.accent_assessment_schemas import (
    RebaselineSchema,
    SelectTargetAccentSchema,
    SubmitDisputeSchema,
)

logger = logging.getLogger(__name__)

# Module-level singletons — same lazy-kv_store-backed pattern as the lib
# services themselves (each defaults `store` to lib.kv_store.store, the
# real Prisma-backed KvEntry table, so this is real persistence, not
# in-memory-only).
_pipeline_service = AccentProfilePipelineService()
_staleness_service = AccentProfileStalenessService(pipeline_service=_pipeline_service)
_dispute_service = ScoreDisputeService()
_target_accent_service = TargetAccentSelectionService()

DEFAULT_TARGET_ACCENT_ID = "general_american"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── shared helpers ──────────────────────────────────────────────────────────
async def _current_target_accent_id(user_id: str) -> str:
    pref = await _target_accent_service.get_preference(user_id)
    return pref.current_accent_id if pref else DEFAULT_TARGET_ACCENT_ID


def _find_assessment(profile: AccentProfile, assessment_id: str) -> Optional[AccentAssessmentResult]:
    for res in profile.baselines_history + profile.drills_history:
        if res.assessment_id == assessment_id:
            return res
    return None


# ── US-82 / ACC-US-03: Target Accent Selection ──────────────────────────────
async def list_target_accents(user_id: str) -> Dict:
    return {"accents": [a.__dict__ for a in _target_accent_service.registry.list_options()]}


async def get_target_accent(user_id: str) -> Dict:
    pref = await _target_accent_service.get_preference(user_id)
    if pref is None:
        return {"current_accent_id": None, "history": []}
    return {
        "current_accent_id": pref.current_accent_id,
        "history": [e.__dict__ for e in pref.history],
    }


async def select_target_accent(user_id: str, payload: SelectTargetAccentSchema) -> Dict:
    result = await _target_accent_service.select_target_accent(
        user_id, payload.accent_id, local_calibration_active=payload.local_calibration_active,
    )
    return {
        "accent": result.accent.__dict__,
        "requested_accent_id": result.requested_accent_id,
        "was_unsupported_request": result.was_unsupported_request,
        "fallback_message": result.fallback_message,
        "confirmation_message": result.confirmation_message,
        "is_mid_history_switch": result.is_mid_history_switch,
    }


# ── shared profile read (feeds US-84's UI + US-83's dispute picker) ────────
async def get_profile(user_id: str) -> Dict:
    profile = await _pipeline_service.get_profile(user_id)
    if profile is None:
        return {"has_profile": False, "baselines_history": [], "drills_history": []}
    return {
        "has_profile": True,
        "target_accent_id": profile.target_accent_id,
        "created_at": profile.created_at.isoformat(),
        "last_assessment_at": profile.last_assessment_at.isoformat(),
        "dismiss_count": profile.dismiss_count,
        "is_reset_baseline": profile.is_reset_baseline,
        "baselines_history": [_assessment_summary(b) for b in profile.baselines_history],
        "drills_history": [_assessment_summary(d) for d in profile.drills_history],
    }


def _assessment_summary(res: AccentAssessmentResult) -> Dict:
    return {
        "assessment_id": res.assessment_id,
        "timestamp": res.timestamp.isoformat(),
        "overall_score": res.overall_score,
        "metrics": {k: v.score for k, v in res.metrics.items()},
        "assessment_type": res.assessment_type,
        "is_historical": res.is_historical,
        "is_audio_available": res.is_audio_available,
        "notice": res.notice,
    }


# ── US-84 / ACC-US-05: Profile Staleness & Re-Baseline ──────────────────────
async def check_staleness(user_id: str) -> Dict:
    details = await _staleness_service.check_staleness_on_login(user_id)
    return {
        "profile_age_days": details.profile_age_days,
        "is_stale": details.is_stale,
        "should_prompt": details.should_prompt,
        "prompt_message": details.prompt_message,
        "prompt_frequency": details.prompt_frequency,
        "suggested_rebaseline_type": details.suggested_rebaseline_type,
        "notice": details.notice,
        "last_assessment_at": details.last_assessment_at.isoformat() if details.last_assessment_at else None,
    }


async def dismiss_staleness_prompt(user_id: str) -> Dict:
    profile = await _staleness_service.dismiss_prompt(user_id)
    return {"dismiss_count": profile.dismiss_count, "last_dismissed_at": profile.last_dismissed_at.isoformat()}


async def rebaseline(user_id: str, payload: RebaselineSchema) -> Dict:
    """
    US-84 happy path: "retake a quick baseline". Reuses a specific
    completed conversation session's real scores (never a client-supplied
    number) as the new baseline's metrics, so this can't be used to fake a
    score. Never overwrites `baselines_history` (execute_rebaseline appends).
    """
    from lib import kv_store
    from services import conversation_service

    session = await kv_store.store.get(conversation_service.NAMESPACE, payload.session_id)
    if session is None or session["user_id"] != user_id:
        return JSONResponse(status_code=404, content={"error": f"Conversation session {payload.session_id} not found"})
    if session["status"] != "completed" or "fluency_score" not in session:
        return JSONResponse(status_code=422, content={
            "error": "That session hasn't completed scoring yet — end the conversation first, then re-baseline from it.",
        })

    metric_scores = {
        "fluency": session["fluency_score"],
        "vocabulary": session["vocabulary_score"],
        "pronunciation": session["pronunciation_score"],
    }
    target_accent_id = await _current_target_accent_id(user_id)
    result = await _staleness_service.execute_rebaseline(
        user_id, metric_scores, target_accent_id=target_accent_id, audio_clip_id=payload.session_id,
    )
    return {
        "assessment_id": result.assessment_id,
        "timestamp": result.timestamp.isoformat(),
        "overall_score": result.overall_score,
        "metrics": {k: v.score for k, v in result.metrics.items()},
        "assessment_type": result.assessment_type,
        "notice": result.notice,
    }


async def record_conversation_drill(user_id: str, session_id: str, metric_scores: Dict[str, float]) -> None:
    """
    Called (best-effort, from conversation_service._end_session) every time
    a conversation ends with real scores. Appends to AccentProfile.drills_history
    so US-83 disputes have something real to reference; on a user's very
    first conversation, also establishes their initial baseline (via
    AccentProfilePipelineService.get_profile/save_profile — the same public
    read/write surface a caller outside this file would use, no changes to
    profile_pipeline.py itself) so US-84 staleness tracking has a real
    starting point instead of never triggering for users who never take a
    dedicated "baseline" action.
    """
    now = _now()
    target_accent_id = await _current_target_accent_id(user_id)
    metrics = {name: ScoredMetric(metric_name=name, score=score, audio_clip_id=session_id)
               for name, score in metric_scores.items()}
    drill = AccentAssessmentResult(
        assessment_id=session_id,
        user_id=user_id,
        timestamp=now,
        metrics=metrics,
        overall_score=calculate_overall_accent_score(metrics),
        target_accent_id=target_accent_id,
        assessment_type="drill",
        audio_clip_id=session_id,
        is_audio_available=False,  # honest: this backend never persists raw audio
    )

    profile = await _pipeline_service.get_profile(user_id)
    if profile is None:
        profile = AccentProfile(
            user_id=user_id, target_accent_id=target_accent_id,
            created_at=now, last_assessment_at=now,
            baselines_history=[drill], drills_history=[],
        )
        logger.info("Accent profile initialized for %s from first conversation session %s", user_id, session_id)
    else:
        profile.drills_history.append(drill)
    await _pipeline_service.save_profile(profile)


# ── US-83 / ACC-US-04: Score Dispute ────────────────────────────────────────
async def get_disputes(user_id: str) -> Dict:
    disputes = await _dispute_service.get_user_disputes(user_id)
    remaining = await _dispute_service.get_remaining_daily_disputes(user_id)
    return {
        "disputes": [_dispute_summary(d) for d in sorted(disputes, key=lambda d: d.created_at, reverse=True)],
        "remaining_allowance": remaining,
        "max_daily_allowance": _dispute_service.max_disputes_per_day,
    }


def _dispute_summary(d) -> Dict:
    return {
        "dispute_id": d.dispute_id,
        "assessment_id": d.assessment_id,
        "metric_name": d.metric_name,
        "original_score": d.original_score,
        "reason": d.reason,
        "user_comment": d.user_comment,
        "status": d.status,
        "audio_available": d.audio_available,
        "created_at": d.created_at.isoformat(),
        "revised_score": d.revised_score,
        "auto_flagged_for_content_team": d.auto_flagged_for_content_team,
        "notification": d.notification,
    }


async def submit_dispute(user_id: str, payload: SubmitDisputeSchema) -> Dict:
    profile = await _pipeline_service.get_profile(user_id)
    assessment = _find_assessment(profile, payload.assessment_id) if profile else None
    if assessment is None:
        return JSONResponse(status_code=404, content={
            "error": f"No scored assessment '{payload.assessment_id}' found for this user.",
        })

    result = await _dispute_service.submit_dispute(
        user_id, assessment, payload.metric_name, payload.reason, user_comment=payload.user_comment,
    )
    if not result.success:
        status = 429 if "limit reached" in (result.error_message or "") else 422
        return JSONResponse(status_code=status, content={
            "error": result.error_message,
            "remaining_allowance": result.remaining_allowance,
            "max_daily_allowance": result.max_daily_allowance,
            "offer_reassessment": result.offer_reassessment,
        })
    return {
        "success": True,
        "dispute": _dispute_summary(result.dispute),
        "remaining_allowance": result.remaining_allowance,
        "max_daily_allowance": result.max_daily_allowance,
        "auto_flagged_for_content_team": result.auto_flagged_for_content_team,
        "notice": result.notice,
    }


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI controllers
# ═══════════════════════════════════════════════════════════════════════════
async def target_accents_endpoint(user_id: str = Depends(require_auth)):
    return await list_target_accents(user_id)


async def get_target_accent_endpoint(user_id: str = Depends(require_auth)):
    return await get_target_accent(user_id)


async def select_target_accent_endpoint(payload: SelectTargetAccentSchema, user_id: str = Depends(require_auth)):
    return await select_target_accent(user_id, payload)


async def get_profile_endpoint(user_id: str = Depends(require_auth)):
    return await get_profile(user_id)


async def check_staleness_endpoint(user_id: str = Depends(require_auth)):
    return await check_staleness(user_id)


async def dismiss_staleness_endpoint(user_id: str = Depends(require_auth)):
    return await dismiss_staleness_prompt(user_id)


async def rebaseline_endpoint(payload: RebaselineSchema, user_id: str = Depends(require_auth)):
    return await rebaseline(user_id, payload)


async def get_disputes_endpoint(user_id: str = Depends(require_auth)):
    return await get_disputes(user_id)


async def submit_dispute_endpoint(payload: SubmitDisputeSchema, user_id: str = Depends(require_auth)):
    return await submit_dispute(user_id, payload)
