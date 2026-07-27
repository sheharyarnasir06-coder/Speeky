"""
Rewrite feature service — the Post-Session Actionable Script trio.

  - US-158 generate_rewrite : personalize a rewrite to the learner's level
  - US-156 score_rewrite    : quantify how much the rewrite improves the original
  - US-159 explain_rewrite  : explain each significant change

All three degrade gracefully: when GROQ isn't configured (or the call/JSON
fails) they fall back to deterministic heuristics, mirroring how
coaching_service / ai_client behave — so the endpoints and tests run offline.

Stateless: no DB writes. The only DB read is the learner's level for
auto-personalization (US-158), and that is best-effort.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from fastapi import Depends

from lib import llm_client
from lib.prisma_client import db
from middlewares.auth_middleware import require_auth
from schemas.rewrite_schemas import (
    ChangeExplanation,
    DifficultyLevel,
    DimensionScore,
    ExplainRewriteRequest,
    ExplainRewriteResponse,
    GenerateRewriteRequest,
    GenerateRewriteResponse,
    ScoreRewriteRequest,
    ScoreRewriteResponse,
    ValidateRewriteRequest,
    ValidationResult,
)
from utils.feature_errors import InvalidSubmissionError

logger = logging.getLogger(__name__)

MIN_WORDS = 3  # anything shorter isn't a rewritable "response"
MAX_GENERATION_ATTEMPTS = 2  # US-161: generate+self-check attempts (1 LLM call each)

SCORE_DIMENSIONS = [
    "grammar",
    "professional_tone",
    "vocabulary",
    "sentence_organization",
    "conciseness",
]
CHANGE_CATEGORIES = {"grammar", "vocabulary", "tone", "conciseness", "structure"}

# US-159 E-01: the exact reassurance copy the story specifies for "no meaningful changes".
NO_MEANINGFUL_CHANGES_MESSAGE = "Your original wording was already effective."
# US-156 E-01: praise the original instead of inflating non-existent improvements.
NO_SIGNIFICANT_IMPROVEMENT_MESSAGE = (
    "Excellent original response — it was already effective, so little needed changing."
)

# US-156 E-01/E-02: the original was already strong only when the average is below
# this AND no single axis clearly improved. A big win on one axis (e.g. grammar) must
# not be diluted to "no significant improvement" by axes that legitimately stayed at 50.
SIGNIFICANCE_THRESHOLD = 55
SINGLE_AXIS_SIGNIFICANCE = 65


def _is_significant(dimension_scores: List[int]) -> bool:
    if not dimension_scores:
        return False
    average = sum(dimension_scores) / len(dimension_scores)
    return average >= SIGNIFICANCE_THRESHOLD or max(dimension_scores) >= SINGLE_AXIS_SIGNIFICANCE

# US-158: how each tier steers the rewrite's register/complexity.
DIFFICULTY_GUIDANCE = {
    DifficultyLevel.BEGINNER: (
        "Use simple, everyday words and short, clear sentences. Avoid idioms and jargon. "
        "Prioritize being easy to understand over sounding sophisticated."
    ),
    DifficultyLevel.INTERMEDIATE: (
        "Use clear, natural professional English with moderate vocabulary. "
        "Well-structured sentences, no unnecessary complexity."
    ),
    DifficultyLevel.ADVANCED: (
        "Use confident, polished professional language with strong verbs and precise word choice. "
        "Varied sentence structure, but still concise."
    ),
    DifficultyLevel.EXECUTIVE: (
        "Use crisp, high-impact executive register: authoritative, outcome-focused, and concise. "
        "Lead with the point. No filler, no hedging."
    ),
}

# US-158: map the stored 6-value LearningLevel onto the 4 rewrite tiers.
LEVEL_MAP = {
    "BEGINNER": DifficultyLevel.BEGINNER,
    "ELEMENTARY": DifficultyLevel.BEGINNER,
    "INTERMEDIATE": DifficultyLevel.INTERMEDIATE,
    "UPPER_INTERMEDIATE": DifficultyLevel.INTERMEDIATE,
    "ADVANCED": DifficultyLevel.ADVANCED,
    "PROFICIENT": DifficultyLevel.EXECUTIVE,
}


# ── helpers ───────────────────────────────────────────────────────────────────
def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _require_rewritable(text: str) -> None:
    if _word_count(text) < MIN_WORDS:
        raise InvalidSubmissionError(
            "Please provide at least a short sentence to work with."
        )


def _clamp_score(v, default: int = 50) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


async def _resolve_difficulty(
    user_id: str, requested: Optional[DifficultyLevel]
) -> Tuple[DifficultyLevel, bool]:
    """Return (level, auto_detected). Manual override wins; otherwise map the
    learner's stored level, defaulting to INTERMEDIATE (US-158 E-01)."""
    if requested is not None:
        return requested, False
    try:
        user = await db.user.find_unique(where={"id": user_id})
        raw = getattr(user, "learningLevel", None) if user else None
        if raw is not None:
            key = str(getattr(raw, "value", raw)).upper().split(".")[-1]
            mapped = LEVEL_MAP.get(key)
            if mapped is not None:
                return mapped, True
    except Exception as e:  # best-effort personalization — never block the rewrite
        logger.warning("level auto-detect failed (%s); defaulting to intermediate", e)
    return DifficultyLevel.INTERMEDIATE, False


# ── US-158: Personalized Rewrite Difficulty ───────────────────────────────────
def _offline_generate(original: str) -> str:
    """Deterministic light cleanup when the LLM is unavailable — trims filler and
    tidies capitalization/terminal punctuation without inventing content."""
    text = re.sub(r"\s+", " ", (original or "").strip())
    for filler in ("um", "uh", "like", "you know", "basically", "actually"):
        text = re.sub(rf"\b{filler}\b,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        text = text[0].upper() + text[1:]
        if text[-1] not in ".!?":
            text += "."
    return text or original


async def _generate_and_check(
    original: str, context: Optional[str], level: DifficultyLevel, corrective: str = ""
) -> Tuple[str, ValidationResult]:
    """One LLM round-trip that BOTH rewrites and self-checks (US-161's quality gate).

    Folding the gate into the generation call keeps the cost at a single LLM request
    per attempt (rather than a second validation call), which matters under provider
    token/rate limits. Raises LLMError on failure."""
    context_line = f"Context: {context}\n" if context else ""
    system = (
        "You are a spoken-English communication coach. Rewrite the user's text so it is "
        "clearer, more professional, and more effective. Preserve the user's original facts, "
        "meaning, and intent EXACTLY — never invent new skills, achievements, numbers, or "
        f"details that are not in the original. {DIFFICULTY_GUIDANCE[level]} "
        f"Then review your own rewrite STRICTLY and honestly, as a critic would. {_rubric(level)} "
        'Respond ONLY as JSON: {"rewrite": "<text>", "checks": '
        '{"fact_preservation": true, ...}, "issues": ["..."]}.'
    )
    if corrective:
        system += f" The previous attempt was rejected for these reasons — fix them: {corrective}"
    raw = await llm_client.chat_json(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{context_line}Original: {original}"},
        ],
        temperature=0.4,
        max_tokens=600,
    )
    rewrite = (raw.get("rewrite") or "").strip()
    if not rewrite:
        raise llm_client.LLMError("empty rewrite")
    raw_checks = raw.get("checks") or {}
    checks = {name: bool(raw_checks.get(name, True)) for name in VALIDATION_CHECKS}
    issues = [str(i) for i in (raw.get("issues") or []) if str(i).strip()]
    validation = ValidationResult(
        passed=all(checks.values()), validated=True, checks=checks, issues=issues
    )
    return rewrite, validation


async def generate_rewrite(
    payload: GenerateRewriteRequest, user_id: str = Depends(require_auth)
) -> GenerateRewriteResponse:
    _require_rewritable(payload.original)
    level, auto = await _resolve_difficulty(user_id, payload.difficulty)

    def _offline_response() -> GenerateRewriteResponse:
        # LLM unavailable (not configured, or a transport/rate-limit error): the best we
        # can do is a light cleanup. generated_by="offline" tells the UI to flag it, so a
        # near-passthrough is never mistaken for a real rewrite.
        return GenerateRewriteResponse(
            original=payload.original,
            rewrite=_offline_generate(payload.original),
            difficulty_used=level,
            auto_detected=auto,
            generated_by="offline",
            validation=ValidationResult(passed=True, validated=False),
            attempts=1,
        )

    if not llm_client.is_configured():
        return _offline_response()

    # US-161: generate + self-check in ONE call per attempt; regenerate (at most
    # MAX_GENERATION_ATTEMPTS) only if the gate fails, feeding the issues back in. After
    # the last attempt we surface the best rewrite with its (failing) checks rather than
    # hard-fail, so the learner always gets something.
    corrective = ""
    last: Optional[Tuple[str, ValidationResult]] = None
    try:
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            rewrite, validation = await _generate_and_check(
                payload.original, payload.context, level, corrective
            )
            last = (rewrite, validation)
            if validation.passed or attempt == MAX_GENERATION_ATTEMPTS:
                return GenerateRewriteResponse(
                    original=payload.original,
                    rewrite=rewrite,
                    difficulty_used=level,
                    auto_detected=auto,
                    generated_by="llm",
                    validation=validation,
                    attempts=attempt,
                )
            corrective = "; ".join(validation.issues) or "Improve overall quality."
        # Unreachable (loop always returns on the last attempt), but keeps types happy.
        rewrite, validation = last  # type: ignore[misc]
        return GenerateRewriteResponse(
            original=payload.original, rewrite=rewrite, difficulty_used=level,
            auto_detected=auto, generated_by="llm", validation=validation,
            attempts=MAX_GENERATION_ATTEMPTS,
        )
    except llm_client.LLMError as e:
        logger.warning("rewrite generation failed (%s); using offline cleanup", e)
        return _offline_response()


# ── US-161: Rewrite Reliability & Quality Validation ──────────────────────────
VALIDATION_CHECKS = [
    "fact_preservation",
    "tone_consistency",
    "professional_vocabulary",
    "readability",
    "no_hallucination",
    "context_preservation",
]


def _rubric(level: DifficultyLevel) -> str:
    """The single quality rubric shared by BOTH gate call sites — the in-generation
    self-check and the standalone /validate endpoint — so the two can never drift and
    disagree about the same {original, rewrite} pair.

    Wording matters: raising the register is the feature's whole purpose, so
    tone_consistency must judge *appropriateness for the target level*, not similarity
    to the original's casual tone. Likewise a faithful paraphrase ("I work hard" ->
    "strong work ethic") is NOT a hallucination — only genuinely new facts are."""
    return (
        "Judge these six booleans (true = passes): "
        "fact_preservation — no NEW facts, skills, numbers, employers, or credentials that "
        "aren't in the original, and none of the original's facts dropped or contradicted; "
        "rewording the same fact more professionally is fine and still passes. "
        "tone_consistency — the tone is consistent within itself and APPROPRIATE for the "
        f"'{level.value}' target register; becoming more polished/formal than the original is "
        "the intended goal and must NOT be marked false. "
        f"professional_vocabulary — word choice suits the '{level.value}' level and is not "
        "needlessly complex. "
        "readability — clear and easy to follow. "
        "no_hallucination — invents no new claims or specifics; faithful paraphrase passes. "
        "context_preservation — keeps the original intent and subject matter. "
        "For every FALSE check add a short reason to issues; if all pass, issues is empty."
    )


async def _validate_rewrite(
    original: str, rewrite: str, level: DifficultyLevel
) -> ValidationResult:
    """Quality gate. Returns validated=False (and passed=True) when the LLM is
    unavailable — the gate is skipped rather than blocking the rewrite."""
    if not llm_client.is_configured():
        return ValidationResult(passed=True, validated=False)

    system = (
        "You are a strict quality-assurance validator for AI-rewritten text. Check the "
        f"REWRITE against the ORIGINAL. {_rubric(level)} Respond ONLY as JSON: "
        '{"checks": {"fact_preservation": true, ...}, "issues": ["..."]}. Include all six checks.'
    )
    user_msg = f"ORIGINAL:\n{original}\n\nREWRITE:\n{rewrite}"
    try:
        raw = await llm_client.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            temperature=0.1,
            max_tokens=600,
        )
        raw_checks = raw.get("checks") or {}
        checks = {name: bool(raw_checks.get(name, True)) for name in VALIDATION_CHECKS}
        issues = [str(i) for i in (raw.get("issues") or []) if str(i).strip()]
        passed = all(checks.values())
        return ValidationResult(passed=passed, validated=True, checks=checks, issues=issues)
    except llm_client.LLMError as e:
        # Can't validate — don't block; mark as skipped so callers know it's ungated.
        logger.warning("rewrite validation failed (%s); skipping gate", e)
        return ValidationResult(passed=True, validated=False)


async def validate_rewrite(
    payload: ValidateRewriteRequest, user_id: str = Depends(require_auth)
) -> ValidationResult:
    """Standalone quality gate for an arbitrary {original, rewrite} pair (US-161)."""
    _require_rewritable(payload.original)
    level = payload.difficulty or DifficultyLevel.INTERMEDIATE
    return await _validate_rewrite(payload.original, payload.rewrite, level)


# ── US-156: Rewrite Improvement Score ─────────────────────────────────────────
def _offline_score(original: str, rewrite: str) -> ScoreRewriteResponse:
    """Heuristic improvement estimate: rewards tighter wording and richer vocabulary
    without an LLM. Neutral (50) when the two texts are effectively identical."""
    identical = _normalize(original) == _normalize(rewrite)
    o_words = re.findall(r"\b\w+\b", original.lower())
    r_words = re.findall(r"\b\w+\b", rewrite.lower())
    o_div = len(set(o_words)) / max(1, len(o_words))
    r_div = len(set(r_words)) / max(1, len(r_words))

    if identical:
        base = 50
    else:
        conciseness = 60 if len(r_words) <= len(o_words) else 52
        vocabulary = 58 if r_div >= o_div else 50
        base = round((conciseness + vocabulary) / 2) + 3

    dims = [
        DimensionScore(
            name=name,
            score=(50 if identical else base),
            explanation=(
                "The rewrite is essentially identical to your original."
                if identical
                else "Estimated offline; connect the AI grader for a detailed per-axis breakdown."
            ),
        )
        for name in SCORE_DIMENSIONS
    ]
    overall = 50 if identical else base
    significant = _is_significant([d.score for d in dims])
    summary = (
        "Your rewrite tightens the wording and word choice."
        if significant
        else NO_SIGNIFICANT_IMPROVEMENT_MESSAGE
    )
    return ScoreRewriteResponse(
        overall_score=overall,
        dimensions=dims,
        summary=summary,
        significant_improvement=significant,
        graded_by="offline",
    )


async def score_rewrite(
    payload: ScoreRewriteRequest, user_id: str = Depends(require_auth)
) -> ScoreRewriteResponse:
    _require_rewritable(payload.original)

    # An unchanged rewrite is 50 ("no change") by definition — resolve it deterministically
    # instead of asking the model, which can otherwise score identical text as a regression.
    if not llm_client.is_configured() or _normalize(payload.original) == _normalize(payload.rewrite):
        return _offline_score(payload.original, payload.rewrite)

    system = (
        "You are an English writing evaluator. Compare the ORIGINAL to the REWRITE and rate how "
        "much the rewrite improves the original on each axis: grammar, professional_tone, "
        "vocabulary, sentence_organization, conciseness. Score each 0-100 where 50 means no "
        "change, above 50 means the rewrite is better, below 50 means it is worse. For each axis "
        "give a one-sentence explanation of WHERE the improvement (or regression) is — never hide "
        "the reasoning. If the original was already excellent, keep scores near 50 rather than "
        "inflating them. Respond ONLY as JSON: "
        '{"dimensions": [{"name": "grammar", "score": 0-100, "explanation": "..."}, ...], '
        '"summary": "..."}. Include all five named axes.'
    )
    user_msg = f"ORIGINAL:\n{payload.original}\n\nREWRITE:\n{payload.rewrite}"
    try:
        raw = await llm_client.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            max_tokens=1000,
        )
        by_name: Dict[str, Dict] = {}
        for d in raw.get("dimensions") or []:
            if isinstance(d, dict) and d.get("name") in SCORE_DIMENSIONS:
                by_name[d["name"]] = d
        dims: List[DimensionScore] = []
        for name in SCORE_DIMENSIONS:
            d = by_name.get(name, {})
            dims.append(
                DimensionScore(
                    name=name,
                    score=_clamp_score(d.get("score")),
                    explanation=str(d.get("explanation") or "No notable change on this axis."),
                )
            )
        overall = round(sum(d.score for d in dims) / len(dims))
        significant = _is_significant([d.score for d in dims])
        # E-01: when nothing meaningfully improved, the story requires praising the
        # original rather than dressing up non-improvements — so the copy is ours, not
        # the model's. When it DID improve, the model's summary explains where (the AC).
        summary = (
            str(raw.get("summary") or "").strip() or "The rewrite is a clear improvement over the original."
            if significant
            else NO_SIGNIFICANT_IMPROVEMENT_MESSAGE
        )
        return ScoreRewriteResponse(
            overall_score=overall,
            dimensions=dims,
            summary=summary,
            significant_improvement=significant,
            graded_by="llm",
        )
    except llm_client.LLMError as e:
        logger.warning("rewrite scoring failed (%s); using offline heuristic", e)
        return _offline_score(payload.original, payload.rewrite)


# ── US-159: Rewrite Explainability ────────────────────────────────────────────
def _offline_explain(original: str, rewrite: str) -> ExplainRewriteResponse:
    if _normalize(original) == _normalize(rewrite):
        return ExplainRewriteResponse(
            changes=[],
            summary=NO_MEANINGFUL_CHANGES_MESSAGE,
            has_meaningful_changes=False,
            explained_by="offline",
        )
    return ExplainRewriteResponse(
        changes=[
            ChangeExplanation(
                category="structure",
                before=original,
                after=rewrite,
                explanation=(
                    "The rewrite adjusts wording and phrasing. Connect the AI coach for a "
                    "detailed, per-change explanation."
                ),
            )
        ],
        summary="The rewrite refines your phrasing.",
        has_meaningful_changes=True,
        explained_by="offline",
    )


async def explain_rewrite(
    payload: ExplainRewriteRequest, user_id: str = Depends(require_auth)
) -> ExplainRewriteResponse:
    _require_rewritable(payload.original)

    # Identical text has nothing to explain (E-01) — decide that here rather than
    # spending an LLM call to be told the same thing.
    if not llm_client.is_configured() or _normalize(payload.original) == _normalize(payload.rewrite):
        return _offline_explain(payload.original, payload.rewrite)

    system = (
        "You are an English writing coach. The user has an ORIGINAL sentence/answer and a REWRITE. "
        "List each significant change the rewrite made so the user can learn to improve on their "
        "own. For every change give: category (one of grammar, vocabulary, tone, conciseness, "
        "structure), the 'before' snippet from the original, the 'after' snippet from the rewrite, "
        "and a short 'explanation' of why it is better. If the rewrite made no meaningful changes, "
        'return an empty changes list. Respond ONLY as JSON: {"changes": [{"category": "...", '
        '"before": "...", "after": "...", "explanation": "..."}], "summary": "..."}.'
    )
    user_msg = f"ORIGINAL:\n{payload.original}\n\nREWRITE:\n{payload.rewrite}"
    try:
        raw = await llm_client.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            max_tokens=1200,
        )
        changes: List[ChangeExplanation] = []
        for c in raw.get("changes") or []:
            if not isinstance(c, dict):
                continue
            category = str(c.get("category") or "").lower().strip()
            if category not in CHANGE_CATEGORIES:
                category = "structure"
            changes.append(
                ChangeExplanation(
                    category=category,
                    before=str(c.get("before") or ""),
                    after=str(c.get("after") or ""),
                    explanation=str(c.get("explanation") or ""),
                )
            )
        if not changes:
            # E-01: no meaningful changes — always the spec's exact reassurance copy, not
            # whatever the model phrased it as, so this branch reads identically to the
            # offline path and to the UI's own empty state.
            return ExplainRewriteResponse(
                changes=[],
                summary=NO_MEANINGFUL_CHANGES_MESSAGE,
                has_meaningful_changes=False,
                explained_by="llm",
            )
        return ExplainRewriteResponse(
            changes=changes,
            summary=str(raw.get("summary") or "").strip()
            or "Here's what changed and why.",
            has_meaningful_changes=True,
            explained_by="llm",
        )
    except llm_client.LLMError as e:
        logger.warning("rewrite explanation failed (%s); using offline fallback", e)
        return _offline_explain(payload.original, payload.rewrite)
