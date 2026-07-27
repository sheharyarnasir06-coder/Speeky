"""
Multi-Language / Configurable Mother-Tongue Code-Switch Detection
(WEC-US-02 / PDF GAP-02).

HONEST LIMITATION, stated up front: TextCodeSwitchDetector's final
approach (Groq word/phrase -> English-equivalent lookup) does not
identify WHICH language a flagged word came from — it only knows "Groq
gave a different equivalent, so it wasn't English." That means true
per-language SCOPING (the spec's actual acceptance criteria —
"cross-reference against the user's configured lexicon(s)") cannot be
implemented with this stack. There is no lexicon anymore, and asking
Groq for a translation doesn't reliably yield a detected source
language either (it would need a second, differently-worded prompt, not
attempted here).

What this module DOES do: track the learner's selected language(s) as
profile metadata, and tag flagged words with that metadata for
LOGGING/reporting purposes. Detection itself is identical to WEC-US-01,
unscoped, for every learner regardless of their language selection.
E-01 (no selection) and E-03 (unsupported language) effectively don't
apply anymore — there's no per-language detection path to disable or
fall back from. This is flagged here rather than faked as "handled."

NOT YET AVAILABLE, flagged:
  - Real learner-profile persistence — in-memory only.
  - Real Word List (CSC-US-02) persistence.
"""

import logging
from typing import Callable, Dict, List, Optional

from .code_switch_text import TextCodeSwitchDetector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LanguageProfileStore:
    """Minimal in-memory learner-language-profile store. TODO: real persistence layer."""

    def __init__(self):
        self._profiles: Dict[str, List[str]] = {}

    def get_languages(self, learner_id: str) -> List[str]:
        return self._profiles.get(learner_id, [])

    def set_languages(self, learner_id: str, language_names: List[str]):
        self._profiles[learner_id] = list(language_names)


class MultiLanguageCodeSwitchDetector:
    """
    Wraps TextCodeSwitchDetector, tagging flagged words with the
    learner's configured language(s) as metadata only. See module
    docstring: this does NOT scope/change detection accuracy per
    language — that isn't achievable with the current stack.
    """

    def __init__(
        self,
        profile_store: Optional[LanguageProfileStore] = None,
        nlp=None,
        word_list_logger: Optional[Callable[[str, str, List[str]], None]] = None,
    ):
        """
        Args:
            profile_store: learner -> selected-language-names. Defaults
                to in-memory LanguageProfileStore.
            nlp: spaCy pipeline, passed through for NER exclusion.
            word_list_logger: callback(word, source, learner_languages)
                — learner_languages is metadata only, not a verified
                per-word language tag (see module docstring).
        """
        self.profile_store = profile_store or LanguageProfileStore()
        self.nlp = nlp
        self.word_list_logger = word_list_logger

    def set_learner_languages(self, learner_id: str, language_names: List[str]):
        """Configure/update a learner's native language(s). Metadata only — does not affect detection."""
        self.profile_store.set_languages(learner_id, language_names)

    async def detect(
        self, learner_id: str, text: str, session_context: Optional[List[str]] = None
    ) -> Dict[str, any]:
        """
        Detect code-switching (identical to WEC-US-01's detection for
        every learner) and tag results with this learner's configured
        language(s) as metadata.

        Async because TextCodeSwitchDetector.detect() is (its translation
        lookup is now a Groq call, see code_switch_text.py) — this just
        propagates that await, output shape is unchanged.
        """
        language_names = self.profile_store.get_languages(learner_id)

        detector = TextCodeSwitchDetector(
            nlp=self.nlp,
            word_list_logger=self._make_scoped_logger(language_names),
        )
        result = await detector.detect(text, session_context=session_context)

        # Attach learner's language metadata to each flagged item —
        # informational tagging only, not a verified per-word source.
        for item in result.get("flagged", []):
            item["learner_languages"] = language_names

        return result

    def _make_scoped_logger(self, language_names: List[str]) -> Optional[Callable[[str, str], None]]:
        if self.word_list_logger is None:
            return None

        def logger_fn(word: str, source: str) -> None:
            self.word_list_logger(word, source, language_names)

        return logger_fn