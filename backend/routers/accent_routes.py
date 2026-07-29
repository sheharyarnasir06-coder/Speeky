from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from middlewares.auth_middleware import require_auth
from services.accent_calibration_service import submit_sub_dialect_dispute
from services.accent_assessment_service import (
    get_target_passage,
    submit_passage_assessment,
)
from services.accent_profile_service import get_exercises, get_profile
from services.accent_tracker_service import get_accent_progress_tracker
from services.targeted_exercise_service import (
    get_targeted_drills,
    skip_targeted_exercises_session,
    submit_targeted_drill_attempt,
)

router = APIRouter()

class SubDialectDisputeSchema(BaseModel):
    dispute_reason: Optional[str] = None

async def handle_sub_dialect_dispute(payload: SubDialectDisputeSchema = SubDialectDisputeSchema(), user_id: str = Depends(require_auth)):
    return await submit_sub_dialect_dispute(user_id, payload.dispute_reason)

# Accent Assessment -- Rhythm & Stress Patterns (US-93)
router.add_api_route("/passages", get_target_passage, methods=["GET"])
router.add_api_route("/passages/{passage_id}/assessments", submit_passage_assessment, methods=["POST"])
router.add_api_route("/sub-dialect-dispute", handle_sub_dialect_dispute, methods=["POST"])

# Accent Profile & Improvement (US-89) — the per-dimension SCORE profile
# (pronunciation/stress/rhythm/intonation/clarity) built from a completed assessment.
# Served under /score-profile, not /profile: /profile belongs to the target-accent
# management profile (accent_assessment_routes) that the client actually fetches, and
# two different payload shapes sharing one path meant whichever router registered first
# silently answered for both.
router.add_api_route("/score-profile", get_profile, methods=["GET"])
router.add_api_route("/score-profile/exercises", get_exercises, methods=["GET"])

# ACC-US-12: Accent Progress Tracker Visualization
router.add_api_route("/progress-tracker", get_accent_progress_tracker, methods=["GET"])

# ACC-US-13: Accent Improvement Targeted Exercises
router.add_api_route("/targeted-drills", get_targeted_drills, methods=["GET"])
router.add_api_route("/targeted-drills/{drill_id}/submit", submit_targeted_drill_attempt, methods=["POST"])
router.add_api_route("/targeted-drills/skip", skip_targeted_exercises_session, methods=["POST"])



