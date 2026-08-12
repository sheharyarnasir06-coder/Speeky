from fastapi import APIRouter

from services.live_call_service import mint_token

router = APIRouter()

# Live Call (LiveKit two-way voice) — mints a room-scoped access token for an
# already-started session; the agent worker (backend/live_call/) attaches
# to that session, it never creates one.
router.add_api_route("/token", mint_token, methods=["POST"])
