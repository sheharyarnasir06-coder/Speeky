"""
Untranslatable / No-Direct-Equivalent Cultural Term Handling
(WEC-US-04 / PDF US-56).

NO HARDCODED LEXICON. Classification heuristic: if a flagged word's
round-trip translation (from code_switch_text.py / code_switch_multilang.py)
comes back as a MULTI-WORD phrase, treat it as "no single-word English
equivalent" -> Cultural Term. Single-word translations -> standard
Target Word (normal code-switch flow, unchanged).

HONEST LIMITATION: "regionally accepted loanword in business English"
(E-02) cannot be detected algorithmically without a hardcoded list.
Caller must supply `whitelisted_loanwords` (e.g. from a config file,
DB table, or admin panel they own) -- this module holds none itself.

Persistence: in-memory only (learner overrides, usage counts, review
queue). TODO: swap for real DB-backed store, same pattern as
LanguageProfileStore in code_switch_multilang.py.
"""

import logging
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TermCategory(str, Enum):
    TARGET_WORD = "target_word"        # standard code-switch, should eliminate
    CULTURAL_TERM = "cultural_term"     # no direct equivalent, generally fine
    UNCLASSIFIED = "unclassified"       # new/unrecognized, queued for review


class CulturalTermClassifier:
    def __init__(
        self,
        whitelisted_loanwords: Optional[Set[str]] = None,
        multi_word_suggestion_threshold: int = 2,
        crutch_usage_threshold: int = 5,
        review_queue_logger: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Args:
            whitelisted_loanwords: caller-supplied set of terms accepted
                as-is in professional English (E-02). NOT populated here.
            multi_word_suggestion_threshold: suggestion word count at/above
                which a flagged item is classified Cultural instead of
                Target (E-01 default-to-cultural-when-uncertain). Not
                spec-defined -- fully overridable.
            crutch_usage_threshold: uses of a Cultural term within one
                learner's recent history before nudging an English
                alternative anyway (E-06). Not spec-defined.
            review_queue_logger: callback(word, learner_id) for surfacing
                Unclassified terms (E-04) to wherever lexicon review
                actually happens -- not implemented here.
        """
        self.whitelisted_loanwords = {w.lower() for w in (whitelisted_loanwords or set())}
        self.multi_word_suggestion_threshold = multi_word_suggestion_threshold
        self.crutch_usage_threshold = crutch_usage_threshold
        self.review_queue_logger = review_queue_logger

        self._manual_overrides: Dict[str, Dict[str, TermCategory]] = {}
        self._usage_counts: Dict[str, Dict[str, int]] = {}

    def classify(self, flagged_item: Dict[str, any], learner_id: str) -> Dict[str, any]:
        """
        Args:
            flagged_item: one entry from TextCodeSwitchDetector /
                MultiLanguageCodeSwitchDetector's "flagged" list
                ({"token", "suggestion", "source", ...}).
        Returns:
            flagged_item augmented with "category" and "note".
        """
        token_key = flagged_item["token"].lower()
        suggestion = (flagged_item.get("suggestion") or "").strip()

        override = self._manual_overrides.get(learner_id, {}).get(token_key)
        if override is not None:
            category = override
        elif token_key in self.whitelisted_loanwords:
            category = TermCategory.CULTURAL_TERM
        elif not suggestion:
            # No translation produced at all -- can't confirm equivalence either way.
            category = TermCategory.UNCLASSIFIED
            if self.review_queue_logger:
                self.review_queue_logger(token_key, learner_id)
        elif len(suggestion.split()) >= self.multi_word_suggestion_threshold:
            # E-01: low confidence in a single-word swap -> default to Cultural.
            category = TermCategory.CULTURAL_TERM
        else:
            category = TermCategory.TARGET_WORD

        note = self._build_note(category, token_key, learner_id)

        return {**flagged_item, "category": category, "note": note}

    def record_manual_reclassify(self, learner_id: str, word: str, category: TermCategory):
        """E-03: learner manually moves a term between categories."""
        self._manual_overrides.setdefault(learner_id, {})[word.lower()] = category

    def record_usage(self, learner_id: str, word: str) -> bool:
        """
        Call once per occurrence of a Cultural-Term word in a learner's
        speech/text. Returns True if usage has crossed the crutch
        threshold (E-06), signalling the caller should nudge an English
        alternative despite the term being generally acceptable.
        """
        counts = self._usage_counts.setdefault(learner_id, {})
        counts[word.lower()] = counts.get(word.lower(), 0) + 1
        return counts[word.lower()] >= self.crutch_usage_threshold

    def _build_note(self, category: TermCategory, word: str, learner_id: str) -> str:
        if category == TermCategory.CULTURAL_TERM:
            if self.record_usage(learner_id, word):
                return (
                    f"'{word}' has no single English equivalent and is generally fine to use, "
                    "but you've leaned on it a lot recently -- want to try an English phrase instead?"
                )
            return f"'{word}' doesn't have a direct English equivalent -- that's okay to use as-is."
        if category == TermCategory.UNCLASSIFIED:
            return f"'{word}' isn't recognized yet -- flagged for review."
        return f"'{word}' has a direct English equivalent worth practicing."