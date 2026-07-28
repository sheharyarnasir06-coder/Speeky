from fastapi import APIRouter

from services.category_service import (
    admin_create_category,
    admin_delete_category,
    admin_list_categories,
    admin_update_category,
    list_categories,
)

router = APIRouter()

# Learner-facing (any authenticated user) — non-empty categories only.
router.add_api_route("/", list_categories, methods=["GET"])

# Admin: full taxonomy management (CM-US-05). Registered before nothing needs to
# worry about path collisions — no catch-all path param on this router.
router.add_api_route("/admin", admin_list_categories, methods=["GET"])
router.add_api_route("/admin", admin_create_category, methods=["POST"])
router.add_api_route("/admin/{category_id}", admin_update_category, methods=["PATCH"])
router.add_api_route("/admin/{category_id}", admin_delete_category, methods=["DELETE"])
