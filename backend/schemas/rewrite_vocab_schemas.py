"""
Vocabulary Mastery Tracking — PSA-US-08 (US-160).

Tracks the advanced vocabulary a rewrite introduced and whether the learner
later uses it naturally in their own practice. Backed by the isolated
RewriteVocabWord table (kept separate from PDG-US-12's VocabularyWordProgress).

The mastery view is paginated server-side (bucket counts via cheap COUNTs, plus
one bounded page of words) so it never loads the whole vocabulary at once.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class IntroduceVocabRequest(BaseModel):
    original: str = Field(..., min_length=1)
    rewrite: str = Field(..., min_length=1)
    context: Optional[str] = Field(None, description="Where the rewrite came from, e.g. 'HR interview'")


class VocabWord(BaseModel):
    word: str
    use_count: int
    status: str            # introduced | practicing | mastered
    needs_review: bool
    introduced_from: Optional[str] = None
    last_used_at: Optional[str] = None


class IntroduceVocabResponse(BaseModel):
    introduced: List[str]      # words now tracked (new this call)
    already_tracked: List[str] # advanced words that were already on the learner's list
    extracted_by: str          # "llm" | "offline"


class VocabCounts(BaseModel):
    mastered: int    # used correctly 3+ times
    practicing: int  # used 1-2 times
    review: int      # introduced but not yet used
    total: int


class PaginatedVocabResponse(BaseModel):
    counts: VocabCounts
    mastery_percentage: int          # mastered / total, 0 when empty
    is_empty: bool                   # nothing introduced yet -> encouraging empty state
    words: List[VocabWord]           # one bounded page, filtered by `status_filter`
    status_filter: str               # all | mastered | practicing | review
    total_filtered: int              # rows matching the active filter
    offset: int
    limit: int
