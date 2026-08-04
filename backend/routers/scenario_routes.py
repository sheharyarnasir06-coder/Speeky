from fastapi import APIRouter

from services.content_intelligence_service import (
    admin_capture_performance_snapshot,
    admin_deployment_confidence,
    admin_deployment_history,
    admin_explain_prompt,
    admin_get_explanation,
    admin_get_vocab_coverage,
    admin_performance_detail,
    admin_score_vocab_coverage,
    rate_session,
)
from services.scenario_service import (
    admin_archive_custom,
    admin_assess_readiness,
    admin_create_custom,
    admin_evaluate_template,
    admin_list_custom,
    admin_list_versions,
    admin_preview_custom,
    admin_restore_custom,
    admin_rollback_custom,
    admin_update_custom,
    end_session,
    get_scenario_detail,
    get_scenarios,
    get_recent_sessions,
    get_session,
    send_turn,
    start_session,
    voice_socket,
)

router = APIRouter()

# Scenario-Based Learning
router.add_api_route("/", get_scenarios, methods=["GET"])
router.add_api_route("/start", start_session, methods=["POST"])
# Registered before "/{key}" so "recent" doesn't get swallowed by the catch-all path param.
router.add_api_route("/recent", get_recent_sessions, methods=["GET"])

# Admin: custom scenario CRUD registered before "/{key}" so doesn't get swallowed by the catch-all path param.
router.add_api_route("/admin/preview", admin_preview_custom, methods=["POST"])
router.add_api_route("/admin/custom", admin_list_custom, methods=["GET"])
router.add_api_route("/admin/custom", admin_create_custom, methods=["POST"])
router.add_api_route("/admin/custom/{scenario_id}", admin_update_custom, methods=["PATCH"])
# DELETE archives rather than hard-deletes (CM-US-04 E-03) — the route name/verb
# frontend already calls stays the same, only the server-side behavior changed.
router.add_api_route("/admin/custom/{scenario_id}", admin_archive_custom, methods=["DELETE"])
router.add_api_route("/admin/custom/{scenario_id}/restore", admin_restore_custom, methods=["POST"])
router.add_api_route("/admin/custom/{scenario_id}/versions", admin_list_versions, methods=["GET"])
router.add_api_route("/admin/custom/{scenario_id}/rollback/{version}", admin_rollback_custom, methods=["POST"])
router.add_api_route("/admin/custom/{scenario_id}/evaluate", admin_evaluate_template, methods=["POST"])
router.add_api_route("/admin/custom/{scenario_id}/readiness", admin_assess_readiness, methods=["POST"])

# Sprint 3 content intelligence. GET returns the cached result (cheap, no LLM);
# POST recomputes. Both stay under /admin/custom/... so the existing
# require_admin-per-handler pattern and the route ordering above still hold.
# US-192 Vocabulary Coverage Score
router.add_api_route("/admin/custom/{scenario_id}/vocab-coverage", admin_get_vocab_coverage, methods=["GET"])
router.add_api_route("/admin/custom/{scenario_id}/vocab-coverage", admin_score_vocab_coverage, methods=["POST"])
# US-195 Prompt Explainability Report
router.add_api_route("/admin/custom/{scenario_id}/explain", admin_get_explanation, methods=["GET"])
router.add_api_route("/admin/custom/{scenario_id}/explain", admin_explain_prompt, methods=["POST"])
# US-193 Template Performance Dashboard (per-template detail + trend snapshot)
router.add_api_route("/admin/custom/{scenario_id}/performance", admin_performance_detail, methods=["GET"])
router.add_api_route("/admin/custom/{scenario_id}/performance/snapshot", admin_capture_performance_snapshot, methods=["POST"])
# US-198 Deployment Confidence Monitoring
router.add_api_route("/admin/custom/{scenario_id}/deployment-confidence", admin_deployment_confidence, methods=["POST"])
router.add_api_route("/admin/custom/{scenario_id}/deployments", admin_deployment_history, methods=["GET"])

router.add_api_route("/{session_id}/turn", send_turn, methods=["POST"])
router.add_api_websocket_route("/{session_id}/voice-ws", voice_socket)
router.add_api_route("/{session_id}/end", end_session, methods=["POST"])
# US-193/US-196 input: a learner rates their own finished session.
router.add_api_route("/sessions/{session_id}/rating", rate_session, methods=["POST"])
router.add_api_route("/sessions/{session_id}", get_session, methods=["GET"])
# Catch-all LAST so none of the literal paths above get swallowed by it.
router.add_api_route("/{key}", get_scenario_detail, methods=["GET"])
