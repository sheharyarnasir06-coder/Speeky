from fastapi import APIRouter, Depends

from lib.explore_sessions import find_open_explore_session, supersede_open_explore_sessions
from middlewares.auth_middleware import require_auth

router = APIRouter()


@router.get("/explore")
async def api_find_open_explore_session(user_id: str = Depends(require_auth)):
    """Unfinished session (any of: conversation, scenario, coaching, interview coach)
    the Explore page uses to show a resume prompt instead of the normal picker."""
    found = await find_open_explore_session(user_id)
    return {"active": found is not None, **(found or {})}


@router.post("/explore/dismiss")
async def api_dismiss_open_explore_session(user_id: str = Depends(require_auth)):
    """The banner's "X" — explicitly ends whatever's open instead of just hiding the
    UI, so it actually stops coming back on the next visit. Same effect a fresh
    start already has (reuses the same supersede call), just without starting
    something new in the same breath."""
    await supersede_open_explore_sessions(user_id)
    return {"dismissed": True}
