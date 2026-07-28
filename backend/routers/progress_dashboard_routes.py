from fastapi import APIRouter
from services.progress_dashboard_service import get_overview, get_progress_dashboard

router = APIRouter()

# Full time-series dashboard (PDG-US-10/14).
router.add_api_route("/progress", get_progress_dashboard, methods=["GET"])
# Flat legacy payload the Vocabulary Growth panel reads — deliberately a different
# shape, not an alias of /progress.
router.add_api_route("/overview", get_overview, methods=["GET"])

