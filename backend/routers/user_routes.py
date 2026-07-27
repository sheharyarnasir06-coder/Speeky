from fastapi import APIRouter

from services.user_service import (
    delete_account,
    get_accent_preference,
    get_profile,
    list_users,
    set_accent_preference,
    request_email_change,
    update_profile,
    update_user_role,
    upload_avatar,
    verify_email_change,
)

router = APIRouter()

# Self-service (auth enforced via Depends(require_auth) on each handler)
# Protected routes (auth enforced via Depends(require_auth) on me() itself,
router.add_api_route("/me", get_profile, methods=["GET"])
router.add_api_route("/me", update_profile, methods=["PATCH"])
router.add_api_route("/me", delete_account, methods=["DELETE"])
# Accent Model Preference toggle (ACC-US-11)
router.add_api_route("/me/accent-preference", get_accent_preference, methods=["GET"])
router.add_api_route("/me/accent-preference", set_accent_preference, methods=["PATCH"])
# Same route handles first upload and later replacement — overwrite is update
router.add_api_route("/me/avatar", upload_avatar, methods=["PATCH"])
# Email changes are OTP-gated: request sends a code to the NEW address,
# verify applies it. Calling request again (e.g. "Resend code") just
# regenerates the code — see EmailChangeOtp upsert in otp_service.
router.add_api_route("/me/email/request-change", request_email_change, methods=["POST"])
router.add_api_route("/me/email/verify-change", verify_email_change, methods=["POST"])


# Admin-only (auth + role enforced via Depends(require_admin) on each handler)
router.add_api_route("/", list_users, methods=["GET"])
router.add_api_route("/{target_user_id}/role", update_user_role, methods=["PATCH"])
