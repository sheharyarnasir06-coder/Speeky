"""
Context-Sensitive Code-Switch Tolerance Across Features
(WEC-US-03 / PDF GAP-03).

Pure Python logic on top of whatever detector is injected (WEC-US-01's
TextCodeSwitchDetector or WEC-US-02's MultiLanguageCodeSwitchDetector,
bound via functools.partial for the latter's learner_id argument). No
LLM, no detection logic of its own — reuses detection results exactly
as returned and applies formality-tier-based tolerance in Python.

Shares the FormalityTier system from formality.py with confidence.py
(BAS-US-11), per this story's own acceptance criteria.
"""

import logging
from typing import Dict, List, Optional, Set

from .formality import FormalityTier, DEFAULT_TIER_WHEN_UNTAGGED

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodeSwitchToleranceWrapper:
    """
    Adjusts code-switch flagging strictness/tone by formality tier, and
    tracks per-word repeat counts so single instances in high-stakes
    contexts don't affect scoring (only repeats do, per E-05).
    """

    DEFAULT_SCORE_IMPACT_REPEAT_THRESHOLD = 2

    def __init__(
        self,
        detector,
        score_impact_repeat_threshold: int = DEFAULT_SCORE_IMPACT_REPEAT_THRESHOLD,
        strictness_by_tier: Optional[Dict[FormalityTier, str]] = None,
    ):
        """
        Args:
            detector: injected detector with `.detect(text,
                session_context=...) -> {"flagged": [...],
                "translation_errors": [...], ...}` (WEC-US-01/02's shape).
            score_impact_repeat_threshold: occurrences of the SAME
                flagged word within a session before it starts affecting
                score (E-05). Fully overridable.
            strictness_by_tier: maps each FormalityTier to a feedback-
                tone label. Defaults below, fully overridable.
        """
        self.detector = detector
        self.score_impact_repeat_threshold = score_impact_repeat_threshold
        self.strictness_by_tier = strictness_by_tier or {
            FormalityTier.CASUAL: "gentle_inline_note",
            FormalityTier.PROFESSIONAL: "explicit_flag",
            FormalityTier.FORMAL_HIGH_STAKES: "explicit_flag_required_correction",
        }
        self._session_word_counts: Dict[str, Dict[str, int]] = {}

    async def evaluate(
        self,
        session_id: str,
        text: str,
        formality_tier: Optional[FormalityTier] = None,
        has_utterance: bool = True,
        scenario_whitelisted_words: Optional[Set[str]] = None,
        session_context: Optional[List[str]] = None,
    ) -> Dict[str, any]:
        """
        Run code-switch detection for one utterance, adjusted for context.

        Async because the injected detector's .detect() is (translation
        lookup is now a Groq call, see code_switch_text.py) — this just
        propagates that await, output shape is unchanged.

        Returns:
            Dict with:
                - flags: list of flagged-word dicts, augmented with
                  "strictness" and "affects_score"
                - formality_tier: the tier actually used
                - feedback_category: always "code_switch_coaching" (E-04)
                - skipped_reason: None, "no_utterance" (E-06), or
                  "translation_errors_present" (some tokens' language was
                  identified but translation failed — surfaced, not
                  silently treated as clean input)
                - translation_errors: passed through from the detector
        """
        if not has_utterance:
            return {
                "flags": [],
                "formality_tier": formality_tier,
                "feedback_category": "code_switch_coaching",
                "skipped_reason": "no_utterance",
                "prompt": None,
                "translation_errors": [],
            }

        tier = formality_tier if formality_tier is not None else DEFAULT_TIER_WHEN_UNTAGGED

        detection_result = await self.detector.detect(text, session_context=session_context)
        translation_errors = detection_result.get("translation_errors", [])

        # BUG FOUND IN TESTING: this method previously read only
        # "flagged"/"translation_errors" and silently dropped
        # "full_sentence_local_language"/"prompt" — a message correctly
        # identified as an entire non-English sentence was returned as
        # if it were clean (flags: [], skipped_reason: None). Fixed:
        # surface it as its own outcome instead of falling through.
        if detection_result.get("full_sentence_local_language"):
            return {
                "flags": [],
                "formality_tier": tier,
                "feedback_category": "code_switch_coaching",
                "skipped_reason": "full_sentence_local_language",
                "prompt": detection_result.get("prompt"),
                "translation_errors": translation_errors,
            }

        whitelist = {w.lower() for w in (scenario_whitelisted_words or set())}
        session_counts = self._session_word_counts.setdefault(session_id, {})

        flags = []
        for item in detection_result.get("flagged", []):
            token_key = item["token"].lower()

            if token_key in whitelist:
                continue  # E-02: scenario explicitly allows this word.

            session_counts[token_key] = session_counts.get(token_key, 0) + 1
            affects_score = session_counts[token_key] >= self.score_impact_repeat_threshold

            flags.append(
                {
                    **item,
                    "strictness": self.strictness_by_tier.get(tier, "explicit_flag"),
                    "affects_score": affects_score,
                }
            )

        return {
            "flags": flags,
            "formality_tier": tier,
            "feedback_category": "code_switch_coaching",
            "skipped_reason": "translation_errors_present" if translation_errors else None,
            "prompt": None,
            "translation_errors": translation_errors,
        }