"""
Code-Switch Word List Router (US-152).

Endpoints:
  GET  /api/code-switch/word-list          → user's word list, sorted by frequency
  PATCH /api/code-switch/word-list/{word}/ignore  → E-01 ignore (false positive)
  DELETE /api/code-switch/word-list/{word}         → E-01 hard remove
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from middlewares.auth_middleware import require_auth
from services import code_switch_service

router = APIRouter(tags=["code-switch"])


@router.get("/word-list")
async def get_word_list(user_id: str = Depends(require_auth)):
    """
    Returns the user's code-switched word list sorted by frequency (E-02).
    Returns empty-state message when list is empty (E-03).
    """
    result = await code_switch_service.get_word_list(user_id)
    return result


@router.patch("/word-list/{word}/ignore")
async def ignore_word(word: str, user_id: str = Depends(require_auth)):
    """
    E-01: Mark a word as ignored (false positive — e.g. a proper noun).
    Ignored words no longer appear in the list and won't be re-logged.
    """
    found = await code_switch_service.ignore_word(user_id, word)
    if not found:
        return JSONResponse(status_code=404, content={"error": f"Word '{word}' not found in your list."})
    return {"success": True, "word": word, "ignored": True}


@router.delete("/word-list/{word}")
async def remove_word(word: str, user_id: str = Depends(require_auth)):
    """
    E-01: Hard-delete a word from the list entirely.
    """
    found = await code_switch_service.remove_word(user_id, word)
    if not found:
        return JSONResponse(status_code=404, content={"error": f"Word '{word}' not found in your list."})
    return {"success": True, "word": word, "removed": True}
