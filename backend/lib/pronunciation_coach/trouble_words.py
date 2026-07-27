"""
Cross-session Trouble Words bank & spaced repetition (Story 4).

Consumes the color tiers produced by the shared PronunciationPipeline
(pronunciation_pipeline.py's ColorTier / WordScoreResult) - it does not
score pronunciation itself, only tracks RED/GRAY outcomes over time per
user, following the same "accumulate in memory, caller drives
persistence" pattern as confidence.py's error_history/session_history.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Set

from nltk.stem import PorterStemmer

from lib.pronunciation_coach.pronunciation_pipeline import ColorTier

logger = logging.getLogger(__name__)

# A word only enters the bank after failing in this many DISTINCT
# sessions (not repeated retries within one session). Named/overridable.
DEFAULT_MIN_FAIL_SESSIONS = 2

# A word is "Mastered" (auto-retired) after this many correct reads across
# separate sessions. Named/overridable.
DEFAULT_MASTERY_CORRECT_SESSIONS = 3

# Active spaced-repetition rotation cap (E-02); beyond this the rest of
# the bank is still viewable via get_archive(), just not actively rotated.
DEFAULT_ACTIVE_ROTATION_CAP = 15

# Only these causes count towards the bank (E-03) - a word flagged red/gray
# because of background noise or a service glitch, not a genuine
# pronunciation error, must never count. This is only the *default* for
# TroubleWordsConfig.excluded_causes below - override/extend it via that
# field (or the TroubleWordsBank(config=...) constructor) rather than
# editing this constant.
CAUSE_NORMAL = "normal"
CAUSE_EXCLUDED = frozenset({"noise", "service_glitch"})

# Fallback pattern-key grouping (E-04) when the caller doesn't supply a
# real phoneme-based `phoneme_pattern_key`. Uses nltk's PorterStemmer -
# nltk is already a direct backend dependency (added alongside g2p_en,
# which pronunciation.py depends on), so this reuses an existing
# dependency rather than adding a new NLP library. PorterStemmer needs no
# downloaded corpus data (pure rule-based algorithm), unlike g2p_en's own
# POS tagger. This is still a coarse surface-form approximation, NOT
# phoneme analysis - real phoneme-pattern grouping should come from
# PronunciationScorer.get_phoneme_errors(...)
# (lib/pronunciation_coach/pronunciation.py) and be passed in via
# `phoneme_pattern_key`, which always takes priority over this fallback
# when supplied.
_stemmer = PorterStemmer()


def _fallback_pattern_key(word: str) -> str:
    return _stemmer.stem(word.lower().strip())


@dataclass
class TroubleWordsConfig:
    min_fail_sessions: int = DEFAULT_MIN_FAIL_SESSIONS
    mastery_correct_sessions: int = DEFAULT_MASTERY_CORRECT_SESSIONS
    active_rotation_cap: int = DEFAULT_ACTIVE_ROTATION_CAP

    # Causes excluded from counting towards the bank (E-03). Defaults to
    # CAUSE_EXCLUDED but is constructor-injectable/extendable, e.g.
    # TroubleWordsConfig(excluded_causes=CAUSE_EXCLUDED | {"low_signal"}),
    # so a caller can add/override excluded causes without editing this file.
    excluded_causes: FrozenSet[str] = field(default_factory=lambda: CAUSE_EXCLUDED)


@dataclass
class DismissalLogEntry:
    pattern_key: str
    dismissed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TroubleWordEntry:
    pattern_key: str
    display_word: str
    fail_sessions: Set[str] = field(default_factory=set)
    correct_sessions: Set[str] = field(default_factory=set)
    related_words: Set[str] = field(default_factory=set)
    status: str = "candidate"  # candidate -> active -> mastered (E-01: mastered -> active on regression)
    manually_dismissed: bool = False
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fail_session_count(self) -> int:
        return len(self.fail_sessions)


class TroubleWordsBank:
    """Per-user in-memory Trouble Words tracking, following confidence.py's in-memory pattern."""

    def __init__(self, config: Optional[TroubleWordsConfig] = None):
        self.config = config or TroubleWordsConfig()
        self._entries: Dict[str, Dict[str, TroubleWordEntry]] = {}  # user_id -> pattern_key -> entry
        self._dismissal_log: Dict[str, List[DismissalLogEntry]] = {}

    def _user_entries(self, user_id: str) -> Dict[str, TroubleWordEntry]:
        return self._entries.setdefault(user_id, {})

    def record_word_result(
        self,
        user_id: str,
        session_id: str,
        word: str,
        tier: ColorTier,
        cause: str = CAUSE_NORMAL,
        phoneme_pattern_key: Optional[str] = None,
    ) -> Optional[TroubleWordEntry]:
        """
        Log one scored word from a session. Only RED/GRAY under a
        `cause` outside config.excluded_causes count towards the bank
        (E-03); GREEN results count towards mastery ONLY for words
        already tracked (i.e. already in the bank).

        Returns the affected entry, or None if this result had no effect
        (e.g. a GREEN result for a word that was never a trouble word).
        """
        if cause in self.config.excluded_causes:
            return None

        key = phoneme_pattern_key or _fallback_pattern_key(word)
        entries = self._user_entries(user_id)

        if tier in (ColorTier.RED, ColorTier.GRAY):
            entry = entries.get(key)
            if entry is None:
                entry = TroubleWordEntry(pattern_key=key, display_word=word)
                entries[key] = entry

            entry.display_word = word
            entry.related_words.add(word.lower())
            entry.fail_sessions.add(session_id)
            entry.last_updated = datetime.now(timezone.utc)

            if entry.status == "mastered":
                # E-01: mastered word regresses -> back to active, reset mastery counter.
                logger.info("Trouble word %r regressed after mastery; resetting counter", key)
                entry.correct_sessions.clear()
                entry.status = "active"
            elif entry.manually_dismissed:
                # E-05: failing again after manual dismissal re-enters normally.
                logger.info("Trouble word %r re-entering after prior manual dismissal", key)
                entry.manually_dismissed = False
                entry.correct_sessions.clear()

            if entry.status == "candidate" and entry.fail_session_count >= self.config.min_fail_sessions:
                entry.status = "active"
                logger.info("Word %r qualifies for Trouble Words bank (key=%s)", word, key)

            return entry

        if tier == ColorTier.GREEN:
            entry = entries.get(key)
            if entry is None or entry.status != "active":
                return None  # not a tracked trouble word; a good read of an untracked word is a no-op

            entry.correct_sessions.add(session_id)
            entry.related_words.add(word.lower())
            entry.last_updated = datetime.now(timezone.utc)

            if len(entry.correct_sessions) >= self.config.mastery_correct_sessions:
                entry.status = "mastered"
                logger.info("Word %r mastered (key=%s)", word, key)

            return entry

        return None  # ORANGE/UNSCORABLE never affect the bank

    def get_active_bank(self, user_id: str) -> List[TroubleWordEntry]:
        """
        Active spaced-repetition rotation: 'active' status, not manually
        dismissed, capped at config.active_rotation_cap by most
        fails / most recent (E-02). The rest of the historical bank is
        still available via get_archive().
        """
        candidates = [
            e for e in self._user_entries(user_id).values() if e.status == "active" and not e.manually_dismissed
        ]
        candidates.sort(key=lambda e: (e.fail_session_count, e.last_updated), reverse=True)
        return candidates[: self.config.active_rotation_cap]

    def get_archive(self, user_id: str) -> List[TroubleWordEntry]:
        """Full historical list regardless of status/cap/dismissal (E-02)."""
        return list(self._user_entries(user_id).values())

    def get_next_review_word(self, user_id: str) -> Optional[TroubleWordEntry]:
        """
        Simple spaced-repetition pick: least-recently-updated word from
        the active rotation, for insertion into a future session's
        sentence set.
        """
        active = self.get_active_bank(user_id)
        if not active:
            return None
        return min(active, key=lambda e: e.last_updated)

    def dismiss_word(self, user_id: str, pattern_key: str) -> None:
        """
        E-05: manual removal from the active bank. Logged as an override
        so that if the word fails again later, record_word_result() lets
        it re-enter normally instead of treating the dismissal as final.
        """
        entry = self._user_entries(user_id).get(pattern_key)
        if entry is None:
            return
        entry.manually_dismissed = True
        self._dismissal_log.setdefault(user_id, []).append(DismissalLogEntry(pattern_key=pattern_key))
        logger.info("User %s manually dismissed trouble word %r", user_id, pattern_key)

    def get_dismissal_log(self, user_id: str) -> List[DismissalLogEntry]:
        return list(self._dismissal_log.get(user_id, []))
