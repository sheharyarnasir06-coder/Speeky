"""
Code-Switch Word Mastery & List Archiving (WEC-US-06 / PDF US-58).

No hardcoded thresholds/lexicon -- everything overridable at construction.
Mastery is tracked by (learner_id, word) key only, independent of which
language a word was tagged under, so a later language-profile change
(WEC-US-02 E-04) never resets progress (E-06 in this story) automatically.

Persistence: in-memory only. TODO: real store.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WordProgress:
    consecutive_clean_opportunities: int = 0
    mastered: bool = False
    manually_marked: bool = False
    last_seen: Optional[datetime] = None
    mastered_at: Optional[datetime] = None


class WordMasteryTracker:
    def __init__(
        self,
        mastery_opportunity_threshold: int = 5,
        likely_mastered_inactivity_days: int = 30,
    ):
        """
        Args:
            mastery_opportunity_threshold: consecutive clean uses before
                a word is marked Mastered. Not spec-defined -- overridable.
            likely_mastered_inactivity_days: days of no relapse before a
                rarely-used flagged word gets "Likely Mastered" (E-02).
        """
        self.mastery_opportunity_threshold = mastery_opportunity_threshold
        self.likely_mastered_inactivity_days = likely_mastered_inactivity_days

        self._progress: Dict[str, Dict[str, WordProgress]] = {}

    def _get(self, learner_id: str, word: str) -> WordProgress:
        learner_words = self._progress.setdefault(learner_id, {})
        return learner_words.setdefault(word.lower(), WordProgress())

    def record_flag(self, learner_id: str, word: str, coaching_enabled: bool = True):
        """Word was code-switched again. Resets streak; relapses a mastered word (E-01)."""
        if not coaching_enabled:
            return  # E-05: excluded from opportunity tracking while coaching is Off.
        p = self._get(learner_id, word)
        p.consecutive_clean_opportunities = 0
        p.last_seen = datetime.utcnow()
        if p.mastered:
            logger.info("Relapse: '%s' returns to active list for learner %s", word, learner_id)
            p.mastered = False
            p.mastered_at = None

    def record_clean_opportunity(self, learner_id: str, word: str, coaching_enabled: bool = True) -> bool:
        """
        Word had a natural opportunity to be code-switched and wasn't.
        Returns True if this call just achieved Mastery.
        """
        if not coaching_enabled:
            return False  # E-05
        p = self._get(learner_id, word)
        p.last_seen = datetime.utcnow()
        if p.mastered:
            return False
        p.consecutive_clean_opportunities += 1
        if p.consecutive_clean_opportunities >= self.mastery_opportunity_threshold:
            p.mastered = True
            p.mastered_at = datetime.utcnow()
            return True
        return False

    def evaluate_session(self, learner_id: str, opportunities: Dict[str, bool],
                          coaching_enabled: bool = True) -> List[str]:
        """
        Batch entry point: opportunities = {word: was_clean_bool} for one
        session. Returns list of words newly Mastered THIS call, so the
        caller can fire one consolidated celebration (E-04) instead of
        one pop-up per word.
        """
        newly_mastered = []
        for word, was_clean in opportunities.items():
            if was_clean:
                if self.record_clean_opportunity(learner_id, word, coaching_enabled):
                    newly_mastered.append(word)
            else:
                self.record_flag(learner_id, word, coaching_enabled)
        return newly_mastered

    def manual_mark_practiced(self, learner_id: str, word: str):
        """E-03: learner-initiated, distinct from system-verified mastery."""
        p = self._get(learner_id, word)
        p.manually_marked = True

    def check_likely_mastered(self, learner_id: str, word: str) -> bool:
        """E-02: rarely-used word, long inactivity with no relapse -> lower-confidence status."""
        p = self._get(learner_id, word)
        if p.mastered or p.last_seen is None:
            return False
        return datetime.utcnow() - p.last_seen >= timedelta(days=self.likely_mastered_inactivity_days)

    def get_active_target_words(self, learner_id: str) -> List[str]:
        return [w for w, p in self._progress.get(learner_id, {}).items() if not p.mastered]

    def get_mastered_words(self, learner_id: str) -> List[str]:
        return [w for w, p in self._progress.get(learner_id, {}).items() if p.mastered]