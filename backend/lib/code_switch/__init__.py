"""
Ported historical code-switch detection & coaching prototypes (US-53,
US-54, US-55, US-56, US-57, US-58).

Originally built as standalone speeky/ modules on an abandoned prototype
branch (`Atika`, never merged into this backend) and restored here
verbatim, only relocated + given a package init - no logic changed. Not
routed through any FastAPI endpoint yet.

Dependency note: code_switch_text.py needs `langdetect` (added to
backend/pyproject.toml) for whole-message language ID. Word/phrase-level
translation lookup goes through this backend's existing Groq client
(lib/llm_client.py) instead of a third-party translation service - no
deep-translator/Google Translate dependency. spaCy (for proper-noun NER
exclusion) is an OPTIONAL soft dependency - code_switch_text.py degrades
gracefully with a logged warning if no `nlp` pipeline is injected; spaCy
itself was NOT added as a dependency here since nothing in this backend
uses it yet.

Async note: TextCodeSwitchDetector.detect(), MultiLanguageCodeSwitchDetector.detect(),
and CodeSwitchToleranceWrapper.evaluate() are all async (the Groq call is
async-only) - callers must await them.
"""

from .formality import DEFAULT_TIER_WHEN_UNTAGGED, FormalityTier
from .code_switch_text import TextCodeSwitchDetector
from .code_switch_multilang import LanguageProfileStore, MultiLanguageCodeSwitchDetector
from .code_switch_tolerance import CodeSwitchToleranceWrapper
from .cultural_terms import CulturalTermClassifier, TermCategory
from .retry_drill import RetryDrillService
from .word_mastery import WordMasteryTracker, WordProgress
from .word_list_store import CodeSwitchedWord, CodeSwitchWordListStore

__all__ = [
    "FormalityTier",
    "DEFAULT_TIER_WHEN_UNTAGGED",
    "TextCodeSwitchDetector",
    "MultiLanguageCodeSwitchDetector",
    "LanguageProfileStore",
    "CodeSwitchToleranceWrapper",
    "CulturalTermClassifier",
    "TermCategory",
    "RetryDrillService",
    "WordProgress",
    "WordMasteryTracker",
    "CodeSwitchedWord",
    "CodeSwitchWordListStore",
]
