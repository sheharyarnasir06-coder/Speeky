from pydantic import BaseModel
from typing import List, Optional


class CodeSwitchedWordSchema(BaseModel):
    """Response schema for one word in the code-switch word list."""
    word: str
    english_equivalent: str
    context_sentences: List[str]
    frequency: int
    ignored: bool
    first_seen: Optional[str] = None


class CodeSwitchWordListResponseSchema(BaseModel):
    """Response for GET /api/code-switch/word-list."""
    words: List[CodeSwitchedWordSchema]
    total: int
    empty_state_message: Optional[str] = None  # E-03


class IgnoreWordSchema(BaseModel):
    """Body for PATCH ignore endpoint (E-01)."""
    word: str
