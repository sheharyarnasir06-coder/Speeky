"""
Text-Mode Code-Switch Detection (WEC-US-01 / PDF GAP-01).

FINAL APPROACH — no Ollama, no local model, no hardcoded lexicon:
  - spaCy: NER proper-noun exclusion (E-01) — unchanged.
  - langdetect: used ONLY for whole-message language ID (E-05). This is
    langdetect's actual designed use case (sentence-level) and testing
    confirmed it works well here. Unchanged.
  - Groq (lib/llm_client, via lib/prompts.build_code_switch_translation_prompt):
    does word/phrase -> English-equivalent lookup for word-level flagging.
    Previously this was deep-translator (GoogleTranslator) round-trip
    diffing; replaced so no separate third-party translation service is
    needed — this backend already talks to Groq everywhere else
    (grammar_checker.py, coaching_service.py, conversation_service.py).

REAL LIMITATIONS, stated plainly:
  - No per-word source-LANGUAGE identification exists in this approach —
    Groq is asked for an equivalent, not a detected source language. This
    means WEC-US-02 cannot truly scope detection BY the learner's
    selected language(s) — see that module's own docstring for how it's
    handled instead. Same limitation as before, different root cause.
  - Groq is a general-purpose chat model, not a dedicated translation
    API: it can ignore the "answer with only the equivalent" instruction
    (add punctuation, a prefix, or turn one word into a full sentence).
    _translate_and_diff() below guards against the last case (rejects
    answers longer than MAX_TRANSLATION_RESPONSE_WORDS) and surfaces
    anything else it can't parse as a translation_errors entry rather
    than trusting it — but this is a heuristic guard, not a guarantee.
  - Real, per-call costs versus a dedicated translation API: every
    flagged token is now a full LLM chat completion — meaningfully
    higher latency (network + generation time, not a lightweight
    translate endpoint) and a per-call cost, and it is subject to Groq's
    account rate limits, unlike a bulk translation API. For a message
    with many non-English tokens, detection time scales with token
    count x one LLM round trip each.
  - Needs live network access + a configured GROQ_API_KEY, same as
    every other Groq-backed feature in this backend. No offline mode —
    when llm_client.is_configured() is False, or the call errors,
    translation is treated as failed (see _translate_and_diff), not
    silently faked.
"""

import logging
from typing import Callable, Dict, List, Optional

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from lib import llm_client, prompts

DetectorFactory.seed = 0  # reproducible sentence-level langdetect results

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Below this token length, translation lookup is treated as too
# unreliable to act on (short strings are noisy for translation systems
# too, not just langdetect). Not spec-defined — practical guard.
MIN_TOKEN_LENGTH_FOR_DETECTION = 4

# E-05: confidence langdetect must report for the WHOLE message before
# treating it as entirely non-English. Not spec-defined — judgment call.
FULL_SENTENCE_CONFIDENCE_THRESHOLD = 0.70

# Groq is asked for "a short, direct English equivalent" (see
# prompts.CODE_SWITCH_TRANSLATION_PROMPT) but, being a chat model rather
# than a translation API, can ignore that and return a full sentence. A
# response longer than this many words is treated as unparseable rather
# than trusted as a translation. Not spec-defined — practical guard.
MAX_TRANSLATION_RESPONSE_WORDS = 4

# Sentinel Groq is instructed to return when the token is already English
# or has no clear equivalent — more reliable than comparing the response
# text back against the original token (which is exactly the kind of
# paraphrase-driven false positive the old deep-translator round-trip
# diffing was vulnerable to, per this module's original docstring).
ALREADY_ENGLISH_SENTINEL = "SAME"

# Deterministic, short output expected — matches grammar_checker.py's
# correct() call shape/temperature for the same kind of single-answer LLM lookup.
TRANSLATION_TEMPERATURE = 0.0
TRANSLATION_MAX_TOKENS = 20


class TextCodeSwitchDetector:
    """
    Detects code-switched words in typed text via round-trip translation
    diffing (word level) and langdetect (sentence level), with spaCy NER
    excluding proper nouns.
    """

    def __init__(
        self,
        nlp=None,
        word_list_logger: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Args:
            nlp: loaded spaCy Language pipeline (reuse the project's
                existing instance) for NER proper-noun exclusion. If
                None, exclusion is skipped with a logged warning.
            word_list_logger: callback(word, source) for wiring to the
                real Code-Switch Word List (CSC-US-02, not built).
        """
        self.nlp = nlp
        self.word_list_logger = word_list_logger

        if self.nlp is None:
            logger.warning(
                "No spaCy pipeline provided — NER proper-noun exclusion (E-01) will be skipped."
            )

    async def detect(self, text: str, session_context: Optional[List[str]] = None) -> Dict[str, any]:
        """
        Scan typed text for code-switched words.

        Now async: translation lookup is a Groq chat completion
        (lib/llm_client), which is async-only, so this method (and its
        two callers in this package — MultiLanguageCodeSwitchDetector.detect()
        and CodeSwitchToleranceWrapper.evaluate()) must be awaited. Output
        shape is unchanged from the deep-translator version.

        Returns:
            Dict with:
                - flagged: list of {"token", "suggestion", "source": "text"}
                  (no "detected_language" — not available with this
                  approach, see module docstring)
                - full_sentence_local_language: bool (E-05)
                - prompt: str or None
                - translation_errors: tokens where translation failed
                  (not configured/network/API/unparseable-response error)
                  — surfaced, not silently dropped
        """
        empty = {
            "flagged": [],
            "full_sentence_local_language": False,
            "prompt": None,
            "translation_errors": [],
        }

        if not text or not text.strip():
            return empty

        tokens = text.split()

        # E-07: single very short message — too unreliable to judge alone.
        if len(tokens) == 1 and len(tokens[0]) <= MIN_TOKEN_LENGTH_FOR_DETECTION:
            logger.info("Single short token '%s' — deferring.", tokens[0])
            return empty

        # BUG FOUND IN TESTING: with the original len(tokens) >= 3 guard,
        # a 3-word message like "send it jaldi" (only ONE non-English
        # word) got misclassified as a full local-language sentence —
        # langdetect is unreliable on short whole-messages too, not just
        # single words. Raised to >= 5 based on that failure; the
        # working full-sentence test case had 8 words, well above this.
        # Still a heuristic guess, not a guaranteed fix.
        if len(tokens) >= 5 and self._looks_like_full_local_sentence(text):
            return {
                "flagged": [],
                "full_sentence_local_language": True,
                "prompt": "It looks like that whole message is in another language. "
                "Could you try writing the full sentence in English?",
                "translation_errors": [],
            }

        proper_nouns = self._get_proper_nouns(text)

        flagged = []
        translation_errors = []

        for raw_token in tokens:
            normalized = self._normalize_token(raw_token)
            if not normalized or len(normalized) < MIN_TOKEN_LENGTH_FOR_DETECTION:
                continue
            if normalized.lower() in proper_nouns:
                continue  # E-01

            suggestion, error = await self._translate_and_diff(normalized, text)
            if error:
                translation_errors.append(raw_token)
                continue
            if suggestion is None:
                continue  # translation matched original -> already English

            flagged.append({"token": raw_token, "suggestion": suggestion, "source": "text"})
            if self.word_list_logger:
                self.word_list_logger(normalized, "text")

        return {
            "flagged": flagged,
            "full_sentence_local_language": False,
            "prompt": None,
            "translation_errors": translation_errors,
        }

    def _normalize_token(self, token: str) -> str:
        """E-06: strip emoji/numbers/decorations before translation."""
        return "".join(ch for ch in token if ch.isalpha())

    async def _translate_and_diff(self, token: str, context: str) -> (Optional[str], bool):
        """
        Ask Groq (lib/llm_client, via prompts.build_code_switch_translation_prompt)
        for a short English equivalent of `token` as used in `context`
        (the full message it came from). Replaces the old deep-translator
        round-trip diff — same (suggestion, had_error) return shape.

        Honesty check on Groq's response: a chat model can ignore
        instructions, so this does NOT blindly trust whatever comes back.
        Treated as had_error=True (an unparseable/failed lookup, not a
        translation) when:
          - Groq isn't configured (no GROQ_API_KEY) or the call raises
            llm_client.LLMError (network/API failure) — same as any
            other Groq-backed feature in this backend.
          - the response is empty after stripping quotes/whitespace.
          - the response is longer than MAX_TRANSLATION_RESPONSE_WORDS —
            i.e. Groq answered with a sentence instead of a short
            equivalent, so it can't be trusted as a clean word/phrase
            suggestion.

        Returns:
            (suggestion_or_None, had_error). suggestion is None if the
            token was already English (Groq returned the ALREADY_ENGLISH_SENTINEL,
            or literally echoed the token back) OR if had_error is True.
        """
        try:
            raw = await llm_client.chat(
                [{"role": "user", "content": prompts.build_code_switch_translation_prompt(token, context)}],
                temperature=TRANSLATION_TEMPERATURE,
                max_tokens=TRANSLATION_MAX_TOKENS,
            )
        except llm_client.LLMError as e:
            logger.error("Groq translation lookup failed for '%s': %s", token, e)
            return None, True

        cleaned = raw.strip().strip('"').strip("'")
        if not cleaned:
            logger.error("Groq returned an empty translation for '%s'", token)
            return None, True

        if len(cleaned.split()) > MAX_TRANSLATION_RESPONSE_WORDS:
            logger.warning(
                "Groq translation response for '%s' looked unparseable (too long): %r", token, raw
            )
            return None, True

        if cleaned.upper() == ALREADY_ENGLISH_SENTINEL or cleaned.lower() == token.strip().lower():
            return None, False  # already English

        return cleaned, False

    def _looks_like_full_local_sentence(self, text: str) -> bool:
        """E-05: langdetect on the WHOLE message — its actual reliable use case."""
        try:
            candidates = detect_langs(text)
        except LangDetectException:
            return False
        if not candidates:
            return False
        top = candidates[0]
        return top.lang != "en" and top.prob >= FULL_SENTENCE_CONFIDENCE_THRESHOLD

    def _get_proper_nouns(self, text: str) -> set:
        """E-01: proper-noun exclusion via spaCy NER — unchanged."""
        if self.nlp is None:
            return set()
        try:
            doc = self.nlp(text)
            return {
                token.text.lower()
                for ent in doc.ents
                if ent.label_ in {"PERSON", "GPE", "LOC", "ORG", "NORP"}
                for token in ent
            }
        except Exception as e:
            logger.error("NER proper-noun check failed: %s", e)
            return set()