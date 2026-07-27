from fastapi import APIRouter
from services.progress_dashboard_service import get_overview, get_progress_dashboard

router = APIRouter()

router.add_api_route("/progress", get_progress_dashboard, methods=["GET"])
router.add_api_route("/overview", get_overview, methods=["GET"])
router.add_api_route("/track", get_progress_dashboard, methods=["GET"])

