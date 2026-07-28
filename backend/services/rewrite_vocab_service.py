"""
Vocabulary Mastery Tracking service — PSA-US-08 (US-160).

Flow:
  introduce  : pull the advanced words a rewrite added (that weren't in the
               original) and seed them on the learner's list as "introduced".
  refresh    : scan the learner's OWN existing practice sessions (scenario +
               coaching) read-only for those words and recompute mastery
               (used 3+ => mastered, 1-2 => practicing, 0 => review). Idempotent
               — recomputed from scratch each call, so repeat refreshes are safe.
  summary    : return the grouped mastery lists + percentage.

Deliberately isolated: its own table (rewrite_vocab_words), and it never writes
to scenario/coaching code or to PDG-US-12's vocabulary_word_progress. The only
cross-feature touch is a read-only query of the learner's own sessions.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import Depends

from lib import llm_client
from lib.prisma_client import db
from middlewares.auth_middleware import require_auth
from schemas.rewrite_vocab_schemas import (
    IntroduceVocabRequest,
    IntroduceVocabResponse,
    PaginatedVocabResponse,
    VocabCounts,
    VocabWord,
)

logger = logging.getLogger(__name__)

MASTERY_THRESHOLD = 3        # mirrors PDG-US-12
DEFAULT_VOCAB_LIMIT = 10     # the panel shows 10 words per page
MAX_VOCAB_LIMIT = 50

# UI filter value -> stored status. "review" is the introduced-but-unused bucket.
_FILTER_TO_STATUS = {"mastered": "mastered", "practicing": "practicing", "review": "introduced"}
MAX_INTRODUCED_PER_CALL = 8  # don't flood the list from one rewrite
MIN_WORD_LEN = 5             # offline heuristic: "advanced" words are longer content words

# Common words never treated as newly-introduced advanced vocabulary (offline path).
_STOPWORDS: Set[str] = {
    "about", "above", "after", "again", "their", "there", "these", "those", "which",
    "while", "would", "could", "should", "because", "before", "being", "between",
    "through", "during", "another", "against", "himself", "herself", "myself",
    "really", "very", "just", "that", "this", "with", "from", "have", "will",
    "your", "you", "they", "them", "then", "than", "into", "over", "some", "such",
    "more", "most", "much", "also", "been", "were", "what", "when", "where",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _words(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def _whole_word_in(word: str, text_lower: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text_lower) is not None


def _offline_extract(original: str, rewrite: str) -> List[str]:
    """Advanced words the rewrite added: content words present in the rewrite,
    absent from the original, long enough and not stopwords."""
    original_set = set(_words(original))
    out: List[str] = []
    seen: Set[str] = set()
    for w in _words(rewrite):
        if (
            w not in original_set
            and w not in _STOPWORDS
            and len(w) >= MIN_WORD_LEN
            and w not in seen
        ):
            seen.add(w)
            out.append(w)
    return out[:MAX_INTRODUCED_PER_CALL]


async def _extract_advanced_words(original: str, rewrite: str) -> Tuple[List[str], str]:
    """(words, extracted_by). LLM picks genuinely upgraded vocabulary; offline
    falls back to the set-difference heuristic."""
    if not llm_client.is_configured():
        return _offline_extract(original, rewrite), "offline"
    system = (
        "Compare the ORIGINAL to the REWRITE. List the advanced or upgraded single vocabulary "
        "words the rewrite introduced that were NOT in the original and are worth the learner "
        "adding to their vocabulary. Only real words, lowercase, no phrases, no proper nouns. "
        'Respond ONLY as JSON: {"words": ["word1", "word2", ...]}.'
    )
    user_msg = f"ORIGINAL:\n{original}\n\nREWRITE:\n{rewrite}"
    try:
        raw = await llm_client.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            max_tokens=300,
        )
        words: List[str] = []
        seen: Set[str] = set()
        original_set = set(_words(original))
        for w in raw.get("words") or []:
            token = str(w).lower().strip()
            if (
                _WORD_RE.fullmatch(token)
                and token not in original_set
                and token not in seen
            ):
                seen.add(token)
                words.append(token)
        return words[:MAX_INTRODUCED_PER_CALL], "llm"
    except llm_client.LLMError as e:
        logger.warning("vocab extraction failed (%s); using offline heuristic", e)
        return _offline_extract(original, rewrite), "offline"


# ── controllers ───────────────────────────────────────────────────────────────
async def introduce_vocab(
    payload: IntroduceVocabRequest, user_id: str = Depends(require_auth)
) -> IntroduceVocabResponse:
    words, extracted_by = await _extract_advanced_words(payload.original, payload.rewrite)

    introduced: List[str] = []
    already: List[str] = []
    for word in words:
        existing = await db.rewritevocabword.find_unique(
            where={"userId_word": {"userId": user_id, "word": word}}
        )
        if existing:
            already.append(word)
            continue
        await db.rewritevocabword.create(
            data={
                "userId": user_id,
                "word": word,
                "status": "introduced",
                "introducedFrom": payload.context or None,
            }
        )
        introduced.append(word)

    return IntroduceVocabResponse(
        introduced=introduced, already_tracked=already, extracted_by=extracted_by
    )


async def _load_session_texts(user_id: str) -> List[Tuple[datetime, str]]:
    """The learner's own practice text, read-only, as (createdAt, lowercased text).
    Scenario user-turns + coaching submissions/turns — where reused vocab shows up."""
    out: List[Tuple[datetime, str]] = []

    scenarios = await db.scenariosession.find_many(where={"userId": user_id})
    for s in scenarios:
        turns = s.turns if isinstance(s.turns, list) else []
        text = " ".join(
            str(t.get("content", "")) for t in turns if isinstance(t, dict) and t.get("role") == "user"
        )
        if text.strip():
            out.append((s.createdAt, text.lower()))

    coachings = await db.coachingsession.find_many(where={"userId": user_id})
    for c in coachings:
        parts: List[str] = [c.submission or ""]
        turns = c.turns if isinstance(c.turns, list) else []
        parts += [
            str(t.get("content", "")) for t in turns if isinstance(t, dict) and t.get("role") == "user"
        ]
        text = " ".join(parts)
        if text.strip():
            out.append((c.createdAt, text.lower()))

    return out


def _status_for(count: int) -> str:
    if count >= MASTERY_THRESHOLD:
        return "mastered"
    if count >= 1:
        return "practicing"
    return "introduced"


async def _recompute(user_id: str) -> None:
    """Recompute every tracked word's usage from the learner's sessions. Idempotent.

    Writes are grouped by target state and flushed with update_many, so the number of
    round-trips scales with the number of DISTINCT outcomes (a handful) rather than with
    the number of tracked words. Per-word updates here were a true N+1: measured 12/32/82
    queries and 1.4s/3.3s/8.1s for 5/25/75 words, which would be ~500 queries for a
    learner with a real vocabulary.
    """
    rows = await db.rewritevocabword.find_many(where={"userId": user_id})
    if not rows:
        return
    sessions = await _load_session_texts(user_id)

    # target state -> ids needing that state. Unused words all collapse into one bucket,
    # which is the overwhelming majority in practice.
    pending: Dict[Tuple[int, str, bool, Optional[datetime]], List[str]] = {}

    for row in rows:
        # Only sessions after the word was introduced count as "future practice".
        matching = [
            created for (created, text) in sessions
            if created >= row.introducedAt and _whole_word_in(row.word, text)
        ]
        count = len(matching)
        status = _status_for(count)
        needs_review = count == 0  # unused vocabulary stays flagged for review (E-02)
        last_used = max(matching) if matching else None

        # Only write when something actually changed — avoids needless updates.
        if (
            row.useCount != count
            or row.status != status
            or row.needsReview != needs_review
            or row.lastUsedAt != last_used
        ):
            pending.setdefault((count, status, needs_review, last_used), []).append(row.id)

    for (count, status, needs_review, last_used), ids in pending.items():
        await db.rewritevocabword.update_many(
            where={"id": {"in": ids}},
            data={
                "useCount": count,
                "status": status,
                "needsReview": needs_review,
                "lastUsedAt": last_used,
            },
        )


def _to_word(row) -> VocabWord:
    return VocabWord(
        word=row.word,
        use_count=row.useCount,
        status=row.status,
        needs_review=row.needsReview,
        introduced_from=row.introducedFrom,
        last_used_at=row.lastUsedAt.isoformat() if row.lastUsedAt else None,
    )


async def _paginated(
    user_id: str, offset: int, limit: int, status_filter: str
) -> PaginatedVocabResponse:
    """Bucket counts via cheap indexed COUNTs, plus one bounded page of words for
    the active filter — never loads the whole vocabulary."""
    offset = max(0, offset)
    limit = max(1, min(limit, MAX_VOCAB_LIMIT))
    status_filter = status_filter if status_filter in _FILTER_TO_STATUS or status_filter == "all" else "all"

    mastered = await db.rewritevocabword.count(where={"userId": user_id, "status": "mastered"})
    practicing = await db.rewritevocabword.count(where={"userId": user_id, "status": "practicing"})
    review = await db.rewritevocabword.count(where={"userId": user_id, "status": "introduced"})
    total = mastered + practicing + review

    where: Dict = {"userId": user_id}
    if status_filter != "all":
        where["status"] = _FILTER_TO_STATUS[status_filter]
    total_filtered = total if status_filter == "all" else await db.rewritevocabword.count(where=where)

    rows = await db.rewritevocabword.find_many(
        where=where,
        order={"introducedAt": "desc"},
        skip=offset,
        take=limit,
    )

    return PaginatedVocabResponse(
        counts=VocabCounts(mastered=mastered, practicing=practicing, review=review, total=total),
        mastery_percentage=round(100 * mastered / total) if total else 0,
        is_empty=(total == 0),
        words=[_to_word(r) for r in rows],
        status_filter=status_filter,
        total_filtered=total_filtered,
        offset=offset,
        limit=limit,
    )


async def get_vocab_mastery(
    offset: int = 0,
    limit: int = DEFAULT_VOCAB_LIMIT,
    status: str = "all",
    user_id: str = Depends(require_auth),
) -> PaginatedVocabResponse:
    """Current mastery state — cheap paginated read, no recompute."""
    return await _paginated(user_id, offset, limit, status)


async def refresh_vocab_mastery(
    offset: int = 0,
    limit: int = DEFAULT_VOCAB_LIMIT,
    status: str = "all",
    user_id: str = Depends(require_auth),
) -> PaginatedVocabResponse:
    """Rescan the learner's practice sessions, update mastery, return the fresh page."""
    await _recompute(user_id)
    return await _paginated(user_id, offset, limit, status)
