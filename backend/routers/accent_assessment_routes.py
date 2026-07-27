from fastapi import APIRouter
from services.target_accent_management_service import (
    check_staleness_endpoint,
    dismiss_staleness_endpoint,
    get_disputes_endpoint,
    get_profile_endpoint,
    get_target_accent_endpoint,
    rebaseline_endpoint,
    select_target_accent_endpoint,
    submit_dispute_endpoint,
    target_accents_endpoint,
)

router = APIRouter(tags=["accent-assessment"])

# US-82 / ACC-US-03: Target Accent Selection
router.add_api_route("/target-accents", target_accents_endpoint, methods=["GET"])
router.add_api_route("/target-accent", get_target_accent_endpoint, methods=["GET"])
router.add_api_route("/target-accent", select_target_accent_endpoint, methods=["POST"])

# Shared profile read (baseline + drill history) — feeds US-84's UI and US-83's dispute picker
router.add_api_route("/profile", get_profile_endpoint, methods=["GET"])

# US-84 / ACC-US-05: Profile Staleness & Re-Baseline Prompt
router.add_api_route("/staleness", check_staleness_endpoint, methods=["GET"])
router.add_api_route("/staleness/dismiss", dismiss_staleness_endpoint, methods=["POST"])
router.add_api_route("/rebaseline", rebaseline_endpoint, methods=["POST"])

# US-83 / ACC-US-04: Score Dispute & Manual Feedback Loop
router.add_api_route("/disputes", get_disputes_endpoint, methods=["GET"])
router.add_api_route("/disputes", submit_dispute_endpoint, methods=["POST"])
