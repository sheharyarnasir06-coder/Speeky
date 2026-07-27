"""
Immediate In-Session Retry & Reinforcement Drill (WEC-US-05 / PDF US-57).

Pure logic on top of whatever detector/tolerance-wrapper is already
producing flagged words (code_switch_text.py, code_switch_tolerance.py).
No detection logic of its own. Reuses FormalityTier from formality.py,
same as confidence.py and code_switch_tolerance.py, per WEC-US-03's own
requirement to share one tier system app-wide.

Persistence: in-memory only (decline streaks). TODO: real store.
"""

import logging
from typing import Callable, Dict, List, Optional, Set

from .formality import FormalityTier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RetryDrillService:
    def __init__(
        self,
        optional_tiers: Optional[Set[FormalityTier]] = None,
        decline_streak_threshold: int = 5,
        word_list_logger: Optional[Callable[[str, str, bool], None]] = None,
    ):
        """
        Args:
            optional_tiers: formality tiers where the retry prompt is
                dismissible rather than default-on. Defaults to
                {CASUAL} per spec (Professional/Formal = default-on).
            decline_streak_threshold: consecutive declines across
                sessions before auto-reducing prompt frequency (E-06).
                Not spec-defined -- overridable.
            word_list_logger: callback(word, source, corrected_on_retry)
                for wiring into the real Word List (CSC-US-02).
        """
        self.optional_tiers = optional_tiers or {FormalityTier.CASUAL}
        self.decline_streak_threshold = decline_streak_threshold
        self.word_list_logger = word_list_logger

        self._decline_streaks: Dict[str, int] = {}

    def evaluate(
        self,
        learner_id: str,
        flags: List[Dict[str, any]],
        formality_tier: FormalityTier,
        is_timed_assessment: bool = False,
    ) -> Dict[str, any]:
        """
        Args:
            flags: this utterance's flagged-word list (e.g. from
                CodeSwitchToleranceWrapper.evaluate()["flags"]).
        Returns:
            Dict with prompt_required, prompt_text (consolidated across
            all flags per E-04), dismissible, suppressed_reason.
        """
        if not flags:
            return {"prompt_required": False, "prompt_text": None,
                     "dismissible": True, "suppressed_reason": "no_flags"}

        if is_timed_assessment:
            # E-05: don't disrupt timing; caller queues flags for post-session review itself.
            return {"prompt_required": False, "prompt_text": None,
                     "dismissible": True, "suppressed_reason": "timed_assessment"}

        if self._decline_streaks.get(learner_id, 0) >= self.decline_streak_threshold:
            # E-06: learner consistently declines -- back off automatically.
            return {"prompt_required": False, "prompt_text": None,
                     "dismissible": True, "suppressed_reason": "auto_reduced_frequency"}

        dismissible = formality_tier in self.optional_tiers
        words = [f["token"] for f in flags]
        suggestions = [f.get("suggestion", "") for f in flags]

        if len(words) == 1:
            prompt_text = f"Try that again using '{suggestions[0]}' instead of '{words[0]}'."
        else:
            pairs = ", ".join(f"'{w}' -> '{s}'" for w, s in zip(words, suggestions))
            prompt_text = f"A few words to retry: {pairs}."  # E-04: consolidated, single prompt.

        return {"prompt_required": True, "prompt_text": prompt_text, "dismissible": dismissible,
                "suppressed_reason": None}

    def record_retry_outcome(self, learner_id: str, word: str, corrected: bool):
        """Learner attempted the retry. Logs outcome, resets decline streak on any attempt."""
        self._decline_streaks[learner_id] = 0
        if self.word_list_logger:
            self.word_list_logger(word.lower(), "retry_drill", corrected)

    def record_decline(self, learner_id: str, word: str):
        """Learner dismissed/ignored the retry prompt (E-01)."""
        self._decline_streaks[learner_id] = self._decline_streaks.get(learner_id, 0) + 1
        if self.word_list_logger:
            self.word_list_logger(word.lower(), "retry_drill", False)