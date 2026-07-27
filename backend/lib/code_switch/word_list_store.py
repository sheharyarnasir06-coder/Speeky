"""
Code-Switch Personal Word List Store (US-152).

Persists detected code-switched words per user via kv_store (same pattern
as AccentProfilePipelineService / session_memory_service). No hardcoding —
English equivalents come from the real Groq translation call in
TextCodeSwitchDetector, passed in by the caller.

Acceptance criteria covered:
- Auto-populated during conversations (caller responsibility, wired in conversation_service)
- Paired with contextual English translation (E-04: stores original sentence)
- Sorted by frequency (E-02)
- Ignore/Remove support (E-01)
- Empty list returns [] (E-03)
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NAMESPACE = "code_switch_word_list"


@dataclass
class CodeSwitchedWord:
    """One tracked code-switched word for a user."""

    word: str                        # original non-English token (lowercased)
    english_equivalent: str          # Groq-produced English translation
    context_sentences: List[str]     # E-04: each sentence the word appeared in
    frequency: int = 1               # E-02: incremented each time the word appears
    ignored: bool = False            # E-01: user marked as false positive
    first_seen: Optional[str] = None # ISO datetime string


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _word_to_dict(w: CodeSwitchedWord) -> Dict[str, Any]:
    return asdict(w)


def _word_from_dict(d: Dict[str, Any]) -> CodeSwitchedWord:
    return CodeSwitchedWord(
        word=d["word"],
        english_equivalent=d["english_equivalent"],
        context_sentences=d.get("context_sentences", []),
        frequency=d.get("frequency", 1),
        ignored=d.get("ignored", False),
        first_seen=d.get("first_seen"),
    )


def _profile_to_dict(user_id: str, words: List[CodeSwitchedWord]) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "words": [_word_to_dict(w) for w in words],
    }


def _profile_from_dict(d: Dict[str, Any]) -> List[CodeSwitchedWord]:
    return [_word_from_dict(w) for w in d.get("words", [])]


class CodeSwitchWordListStore:
    """
    Persistent word-list store backed by kv_store (PrismaKvStore in prod,
    InMemoryKvStore in tests — same swap pattern as every other service).
    """

    def __init__(self, store: Optional[Any] = None):
        self._store = store

    @property
    def store(self) -> Any:
        if self._store is None:
            from lib import kv_store
            self._store = kv_store.store
        return self._store

    async def _load(self, user_id: str) -> List[CodeSwitchedWord]:
        raw = await self.store.get(NAMESPACE, user_id)
        if raw is None:
            return []
        return _profile_from_dict(raw)

    async def _save(self, user_id: str, words: List[CodeSwitchedWord]) -> None:
        existing = await self.store.get(NAMESPACE, user_id)
        data = _profile_to_dict(user_id, words)
        if existing is None:
            await self.store.create(NAMESPACE, user_id, data)
        else:
            await self.store.update(NAMESPACE, user_id, data)

    async def log_word(
        self,
        user_id: str,
        word: str,
        english_equivalent: str,
        context_sentence: str,
    ) -> None:
        """
        Auto-called during conversation turns (US-152 happy path step 2).

        - If word is new → create entry.
        - If word exists and not ignored → increment frequency, append context (E-04).
        - If word is ignored (E-01) → silently skip so ignored words don't come back.
        """
        norm = word.lower().strip()
        if not norm:
            return

        words = await self._load(user_id)
        existing = next((w for w in words if w.word == norm), None)

        if existing is None:
            words.append(CodeSwitchedWord(
                word=norm,
                english_equivalent=english_equivalent,
                context_sentences=[context_sentence],
                frequency=1,
                ignored=False,
                first_seen=_now_iso(),
            ))
            logger.info("US-152: new code-switched word '%s' logged for user %s", norm, user_id)
        elif not existing.ignored:
            existing.frequency += 1
            # E-04: keep each unique context so multiple meanings are visible
            if context_sentence not in existing.context_sentences:
                existing.context_sentences.append(context_sentence)
            logger.info("US-152: frequency for '%s' now %d for user %s", norm, existing.frequency, user_id)
        else:
            logger.debug("US-152: '%s' is ignored for user %s — skipping log", norm, user_id)
            return

        await self._save(user_id, words)

    async def get_list(self, user_id: str, include_ignored: bool = False) -> List[CodeSwitchedWord]:
        """
        Returns words sorted by frequency desc (E-02).
        Filters out ignored words by default (E-01).
        Returns [] when no words exist (E-03).
        """
        words = await self._load(user_id)
        if not include_ignored:
            words = [w for w in words if not w.ignored]
        return sorted(words, key=lambda w: w.frequency, reverse=True)

    async def ignore_word(self, user_id: str, word: str) -> bool:
        """
        E-01: Mark a word as ignored (false positive). Returns True if found.
        Ignored words are excluded from get_list() and future log_word() calls.
        """
        norm = word.lower().strip()
        words = await self._load(user_id)
        target = next((w for w in words if w.word == norm), None)
        if target is None:
            return False
        target.ignored = True
        await self._save(user_id, words)
        logger.info("US-152: word '%s' ignored for user %s", norm, user_id)
        return True

    async def remove_word(self, user_id: str, word: str) -> bool:
        """
        E-01: Hard-delete a word from the list. Returns True if found and removed.
        """
        norm = word.lower().strip()
        words = await self._load(user_id)
        before = len(words)
        words = [w for w in words if w.word != norm]
        if len(words) == before:
            return False
        await self._save(user_id, words)
        logger.info("US-152: word '%s' removed for user %s", norm, user_id)
        return True
