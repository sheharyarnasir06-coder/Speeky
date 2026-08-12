"""
Answer relevance + substance judging — the gate every scored module routes through.

WHY THIS EXISTS
---------------
Before this module, no scorer in the backend compared an answer to the question it was
asked. `question.text` never entered a scoring function; the Interview Coach literally
computed `relevance = clarity + 5`. Combined with scorers that start high and subtract,
that made a fluent answer about pizza score identically to a fluent answer about the
actual question, and made "nothing" score like a real reply.

TWO STAGES, IN THIS ORDER
-------------------------
1. `evaluate_substance` — deterministic, offline-safe, always runs. Catches the things
   that need no judgement: empty, unintelligible, repetitive, non-English, or simply
   too little content to be an answer. Rejecting here means NO LLM call, so the abusive
   inputs are also the cheap ones.
2. `judge_relevance` — the Groq judge, for the case a heuristic genuinely cannot call:
   fluent, well-formed, and about the wrong thing.

The gate can veto the judge (its `substance` caps the judge's). The judge can never
rescue a gate rejection. That asymmetry is deliberate — a model talked into scoring
`asdf asdf` highly should not be able to override arithmetic that knows better.

NO LLM MEANS NO SCORE
---------------------
When Groq is unconfigured or fails, `assess` returns `verdict=UNGRADED`,
`relevance=None`, `source=SOURCE_UNAVAILABLE`. Callers must surface that as "not yet
graded", never as a number. The previous behaviour — silently substituting a heuristic
that started at 88 and calling it a grade — is what this whole module exists to stop.

Pure module: imports nothing from `services/`, so it is unit-testable with no network
and no database (same convention as lib/video_scorer.py).
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from lib import llm_client, prompts

logger = logging.getLogger(__name__)

# ── Verdicts ──────────────────────────────────────────────────────────────────
OK = "ok"
EMPTY = "empty"
UNINTELLIGIBLE = "unintelligible"
NO_SUBSTANCE = "no_substance"
REPETITIVE = "repetitive"
NON_ENGLISH = "non_english"
OFF_TOPIC = "off_topic"
UNGRADED = "ungraded"

#: Verdicts that mean "this is not an answer" — scored 0, and never sent to the LLM.
REJECTED_VERDICTS = frozenset({EMPTY, UNINTELLIGIBLE, NO_SUBSTANCE, REPETITIVE, NON_ENGLISH})

SOURCE_GATE = "gate"
SOURCE_LLM = "llm"
SOURCE_UNAVAILABLE = "unavailable"

# ── Scoring status, shared by every scored module ─────────────────────────────
#: A real grade.
STATUS_SCORED = "scored"
#: The grader could not run (no GROQ_API_KEY, Groq down, unparseable response). Scores are
#: null and the UI must say so. Never substitute a heuristic number here: the entire class
#: of bugs this module was written to fix came from offline fallbacks that produced
#: confident-looking scores the user could not distinguish from real ones.
STATUS_UNAVAILABLE = "unavailable"
#: There was nothing to grade — no answers, no speech, an empty submission.
STATUS_INSUFFICIENT = "insufficient_evidence"

# ── Thresholds ────────────────────────────────────────────────────────────────
#: Below this deterministic substance score there is nothing to grade. Calibrated so a
#: one- or two-word reply ("nothing", "I don't know") falls under it while a genuine
#: short answer does not — see tests/test_relevance.py for the boundary cases.
NO_SUBSTANCE_THRESHOLD = 8.0

#: Share of tokens absent from CMUdict (after suffix normalisation) that marks a
#: submission as unintelligible. Measured separation is wide: real prose with technical
#: jargon lands 0.00-0.20, keyboard mash and invented words land 1.00. 0.60 sits in the
#: gap with room for domain vocabulary the dictionary has never heard of.
UNKNOWN_WORD_RATIO_THRESHOLD = 0.60

#: The unknown-word check needs enough tokens to be meaningful — a three-word answer of
#: proper nouns would otherwise read as gibberish.
MIN_TOKENS_FOR_DICTIONARY_CHECK = 4

#: Mirrors code_switch_text.FULL_SENTENCE_CONFIDENCE_THRESHOLD — langdetect is only
#: trusted on a whole message, at high confidence.
NON_ENGLISH_CONFIDENCE_THRESHOLD = 0.70
MIN_TOKENS_FOR_LANGUAGE_CHECK = 5

#: Repetition / filler detection. Same shape as the Daily Challenge anti-gaming check in
#: lib/quality_scoring.py, which would have been the natural thing to reuse — except that
#: module raises ImportError on import (it pulls three DAILY_CHALLENGE_* constants that
#: do not exist in lib/prompts.py) and has no callers, so reusing it would mean
#: resurrecting dead code on this critical path. Kept separate and explicit instead.
MIN_TOKENS_FOR_REPETITION_CHECK = 6
MIN_UNIQUE_TOKEN_RATIO = 0.35
MAX_DOMINANT_TOKEN_RATIO = 0.45

#: Substance is built up from evidence, never down from a base. Full marks need roughly
#: this much: a paragraph's worth of words carrying this many distinct content words.
SUBSTANCE_FULL_WORD_COUNT = 40
SUBSTANCE_FULL_CONTENT_WORDS = 15
SUBSTANCE_LENGTH_WEIGHT = 60.0
SUBSTANCE_CONTENT_WEIGHT = 40.0

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_CHAR_RUN_RE = re.compile(r"(.)\1{3,}")
_VOWELS = set("aeiouy")

#: Shared with services/rewrite_vocab_service.py, which imports this set rather than
#: keeping its own copy. Kept deliberately small — it only needs to stop the commonest
#: function words from counting as "content" when measuring substance and overlap.
STOPWORDS: Set[str] = {
    "about", "above", "after", "again", "their", "there", "these", "those", "which",
    "while", "would", "could", "should", "because", "before", "being", "between",
    "through", "during", "another", "against", "himself", "herself", "myself",
    "really", "very", "just", "that", "this", "with", "from", "have", "will",
    "your", "you", "they", "them", "then", "than", "into", "over", "some", "such",
    "more", "most", "much", "also", "been", "were", "what", "when", "where",
    "the", "and", "for", "are", "was", "but", "not", "can", "his", "her", "its",
    "our", "who", "why", "how", "all", "any", "had", "has", "did", "does", "done",
}

#: Suffixes stripped before a dictionary lookup, longest first. CMUdict omits many
#: regular inflections ("onboarding", "organised"); without this they read as invented
#: words and a real answer gets gated as gibberish.
_SUFFIXES = ("iness", "ingly", "ising", "izing", "ised", "ized", "ings", "ing", "edly",
             "ies", "ied", "ers", "est", "ely", "ness", "ment", "less", "ful",
             "ed", "es", "er", "ly", "s")


# ── Dictionary lookup ─────────────────────────────────────────────────────────
def _lookup(word: str) -> bool:
    """CMUdict membership via the `pronouncing` dependency already pulled in for the
    Pronunciation Coach — no extra package, no download, works offline."""
    try:
        import pronouncing
    except ImportError:  # pragma: no cover - dependency is declared in pyproject
        logger.warning("pronouncing unavailable; skipping dictionary check")
        return True
    return bool(pronouncing.phones_for_word(word))


def is_known_word(word: str) -> bool:
    """True if the token is a real English word, allowing for regular inflection."""
    w = word.lower().strip("'-")
    if not w:
        return False
    if len(w) <= 2:
        return True  # "a", "I", "ok", "hi" — too short to judge, and never the problem
    if _lookup(w):
        return True
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            stem = w[: -len(suffix)]
            if _lookup(stem) or _lookup(stem + "e") or _lookup(stem + "y"):
                return True
            # doubled final consonant: "running" -> "run"
            if len(stem) >= 4 and stem[-1] == stem[-2] and _lookup(stem[:-1]):
                return True
    return False


# ── Deterministic gate ────────────────────────────────────────────────────────
@dataclass
class GateResult:
    verdict: str
    substance: float  # 0-100 — deterministic ceiling on how much real content exists
    word_count: int
    real_word_ratio: float
    overlap: Optional[float]  # content-word overlap with the question, None if no question
    reason: str

    @property
    def rejected(self) -> bool:
        return self.verdict in REJECTED_VERDICTS


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def content_words(tokens: List[str]) -> Set[str]:
    return {t for t in tokens if t not in STOPWORDS and len(t) >= 3}


def _is_degenerate(token: str) -> bool:
    """A token no human typed as a word: character runs, or a long vowel-less string."""
    if _CHAR_RUN_RE.search(token):
        return True
    return len(token) >= 4 and not (_VOWELS & set(token))


def _repetition_ratios(tokens: List[str]) -> tuple:
    """(unique_ratio, dominant_ratio) — variety of content vs. one word hammered."""
    total = len(tokens)
    if not total:
        return 0.0, 1.0
    unique_ratio = len(set(tokens)) / total
    dominant_ratio = max(tokens.count(t) for t in set(tokens)) / total
    return unique_ratio, dominant_ratio


def _is_repetitive(unique_ratio: float, dominant_ratio: float, token_count: int) -> bool:
    if token_count < MIN_TOKENS_FOR_REPETITION_CHECK:
        return False
    return unique_ratio < MIN_UNIQUE_TOKEN_RATIO or dominant_ratio > MAX_DOMINANT_TOKEN_RATIO


def _looks_non_english(text: str, token_count: int) -> bool:
    if token_count < MIN_TOKENS_FOR_LANGUAGE_CHECK:
        return False
    try:
        from langdetect import LangDetectException, detect_langs
    except ImportError:  # pragma: no cover - dependency is declared in pyproject
        return False
    try:
        candidates = detect_langs(text)
    except LangDetectException:
        return False
    if not candidates:
        return False
    top = candidates[0]
    return top.lang != "en" and top.prob >= NON_ENGLISH_CONFIDENCE_THRESHOLD


def _content_overlap(question: Optional[str], tokens: List[str]) -> Optional[float]:
    """Share of the question's content words that appear in the answer.

    A *signal*, never a verdict: a good answer can paraphrase a question completely and
    share nothing with it. It only nudges substance and is reported for diagnostics.
    """
    if not question:
        return None
    q_content = content_words(tokenize(question))
    if not q_content:
        return None
    return len(q_content & set(tokens)) / len(q_content)


def evaluate_substance(text: str, question: Optional[str] = None) -> GateResult:
    """Deterministic, offline-safe check for whether there is an answer here at all."""
    raw = (text or "").strip()
    if not raw:
        return GateResult(EMPTY, 0.0, 0, 0.0, None, "Empty submission")

    tokens = tokenize(raw)
    word_count = len(tokens)
    if word_count == 0:
        return GateResult(EMPTY, 0.0, 0, 0.0, None, "No words in submission")

    overlap = _content_overlap(question, tokens)

    # Real-word ratio drives both the unintelligible verdict and the substance discount.
    known = sum(1 for t in tokens if is_known_word(t))
    real_word_ratio = known / word_count
    degenerate = sum(1 for t in tokens if _is_degenerate(t))

    if degenerate / word_count > 0.5:
        return GateResult(UNINTELLIGIBLE, 0.0, word_count, real_word_ratio, overlap,
                          "Mostly character runs or vowel-less strings")

    if (word_count >= MIN_TOKENS_FOR_DICTIONARY_CHECK
            and (1.0 - real_word_ratio) > UNKNOWN_WORD_RATIO_THRESHOLD):
        return GateResult(UNINTELLIGIBLE, 0.0, word_count, real_word_ratio, overlap,
                          f"{round((1 - real_word_ratio) * 100)}% of words are not English words")

    unique_ratio, dominant_ratio = _repetition_ratios(tokens)
    if _is_repetitive(unique_ratio, dominant_ratio, word_count):
        return GateResult(REPETITIVE, 0.0, word_count, real_word_ratio, overlap,
                          "Repeated or filler-dominated content")

    if _looks_non_english(raw, word_count):
        return GateResult(NON_ENGLISH, 0.0, word_count, real_word_ratio, overlap,
                          "Submission is not in English")

    # Substance is built up from evidence — length and distinct content — then
    # discounted by how much of it is real language. There is no floor: an answer that
    # demonstrates nothing scores nothing.
    length_part = min(word_count / SUBSTANCE_FULL_WORD_COUNT, 1.0) * SUBSTANCE_LENGTH_WEIGHT
    distinct = len(content_words(tokens))
    content_part = min(distinct / SUBSTANCE_FULL_CONTENT_WORDS, 1.0) * SUBSTANCE_CONTENT_WEIGHT
    substance = round((length_part + content_part) * real_word_ratio, 2)

    if substance < NO_SUBSTANCE_THRESHOLD:
        return GateResult(NO_SUBSTANCE, substance, word_count, real_word_ratio, overlap,
                          "Too little content to assess")

    return GateResult(OK, substance, word_count, real_word_ratio, overlap, "")


# ── LLM judge ─────────────────────────────────────────────────────────────────
@dataclass
class RelevanceResult:
    relevance: Optional[float]  # 0-100, None when ungradeable
    substance: Optional[float]  # 0-100, None when ungradeable
    verdict: str
    source: str
    reason: str
    gate: Optional[GateResult] = None

    @property
    def graded(self) -> bool:
        return self.relevance is not None

    def to_dict(self) -> Dict:
        return {
            "relevance": self.relevance,
            "substance": self.substance,
            "verdict": self.verdict,
            "source": self.source,
            "reason": self.reason,
        }


def _clamp_score(value, default: Optional[float] = None) -> Optional[float]:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


async def judge_relevance(
    question: str,
    answer: str,
    context: Optional[str] = None,
) -> Optional[Dict]:
    """Ask Groq to judge one answer. Returns None when the LLM is unavailable.

    None is a distinct outcome from a low score and must stay that way — callers turn
    it into "not graded", not into zero.
    """
    if not llm_client.is_configured():
        return None
    try:
        raw = await llm_client.chat_json(
            [{"role": "user", "content": prompts.build_answer_relevance_prompt(
                question=question, answer=answer, context=context)}],
            temperature=0.0,
            max_tokens=300,
        )
    except llm_client.LLMError as e:
        logger.warning("Relevance judging failed (%s); answer will be reported ungraded", e)
        return None

    relevance = _clamp_score(raw.get("relevance"))
    substance = _clamp_score(raw.get("substance"))
    if relevance is None:
        logger.warning("Relevance judge returned no usable relevance: %r", raw)
        return None
    return {
        "relevance": relevance,
        "substance": substance if substance is not None else relevance,
        "on_topic": bool(raw.get("on_topic", relevance >= 50)),
        "reason": str(raw.get("reason", ""))[:200],
    }


async def assess(
    question: Optional[str],
    answer: str,
    *,
    context: Optional[str] = None,
) -> RelevanceResult:
    """Full relevance assessment: deterministic gate, then the LLM judge if needed."""
    gate = evaluate_substance(answer, question)
    if gate.rejected:
        return RelevanceResult(0.0, 0.0, gate.verdict, SOURCE_GATE, gate.reason, gate)

    if not question:
        # Nothing to be relevant *to* — substance is the whole story.
        return RelevanceResult(gate.substance, gate.substance, OK, SOURCE_GATE,
                               "No question to compare against", gate)

    judged = await judge_relevance(question, answer, context)
    if judged is None:
        return RelevanceResult(None, None, UNGRADED, SOURCE_UNAVAILABLE,
                               "Grader unavailable", gate)

    # The gate caps the judge: a model that talks itself into a high substance score for
    # thin content does not get to override the arithmetic.
    substance = min(judged["substance"], gate.substance)
    relevance = judged["relevance"]
    verdict = OFF_TOPIC if (relevance < 30 or not judged["on_topic"]) else OK
    return RelevanceResult(relevance, substance, verdict, SOURCE_LLM, judged["reason"], gate)


# ── Applying relevance to a score ─────────────────────────────────────────────
def relevance_multiplier(relevance: Optional[float]) -> float:
    """Convert a relevance score into a factor applied to the language-quality scores.

    Relevance MULTIPLIES rather than adding, so an off-topic answer cannot ride fluency
    and vocabulary to a passing grade. The curve is steep below 40: partial credit for
    "sounded good, answered nothing" is exactly the failure this replaces.

    Returns 0.0 for None so callers that forget to check `graded` fail loud and low
    rather than quietly scoring an ungraded answer as if it were fine.
    """
    if relevance is None:
        return 0.0
    r = max(0.0, min(100.0, float(relevance)))
    if r <= 10:
        return 0.05
    if r <= 30:
        return 0.15 + (r - 10) / 20 * 0.15
    if r <= 50:
        return 0.30 + (r - 30) / 20 * 0.30
    return 0.60 + (r - 50) / 50 * 0.40


def apply(score: Optional[float], relevance: Optional[float]) -> Optional[float]:
    """Scale one sub-score by relevance, preserving None (which means 'not measured')."""
    if score is None:
        return None
    return round(score * relevance_multiplier(relevance), 2)
