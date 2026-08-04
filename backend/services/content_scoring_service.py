"""
Content Management — Template Quality Score, Prompt Confidence Score, and Scenario
Readiness Assessment (CM-US-02, CM-US-06, CM-US-07).

Mirrors scenario_service.grade_session's LLM-with-offline-fallback pattern:
quality+confidence come from one combined Groq call (lib.prompts.
build_template_evaluation_prompt) with a deterministic offline grader when Groq
isn't configured/reachable, same as every other LLM path in this app. Readiness is
pure deterministic checklist logic — it consumes quality/confidence scores but
doesn't itself call the LLM.
"""

import logging
from typing import Dict, List

from lib.scoring import clamp, clean_str_list
from lib import llm_client, prompts

logger = logging.getLogger(__name__)

QUALITY_CONFIDENCE_MIN_TO_PASS = 50  # readiness threshold (CM-US-07)

# CM-US-02: the stricter bar specifically for allowing a scenario to go live. Higher
# than the readiness floor above on purpose — readiness asks "is this complete enough
# to consider", publish asks "is this actually good". Below this, the admin must tick
# quality_acknowledged to publish anyway (the content-safety scan below is separate
# and is NEVER overridable by that flag).
QUALITY_PUBLISH_THRESHOLD = 70


def offline_evaluate_template(scenario: Dict) -> Dict:
    """Deterministic fallback — checks presence/length signals only, no real
    language judgement (that needs the LLM), but keeps every field populated so
    the UI never has to special-case "no score yet"."""
    vocab = scenario.get("target_vocab") or []
    prompt_text = scenario.get("system_prompt") or ""
    intent = scenario.get("intent") or ""

    quality = 50
    recommendations: List[str] = []
    if len(prompt_text) < 120:
        quality -= 15
        recommendations.append("Add more detail to the system prompt — it reads as thin.")
    if len(vocab) < 5:
        quality -= 10
        recommendations.append("Consider adding a few more target vocabulary words.")
    if len(intent) < 30:
        quality -= 10
        recommendations.append("Expand the learner-facing intent for more clarity.")
    if not scenario.get("opening_line"):
        recommendations.append("An opening line makes the scenario start more predictably.")
    if not recommendations:
        recommendations.append("Looks complete — no automatic offline flags.")

    confidence = 55
    warnings: List[str] = []
    guardrails: List[str] = []
    if len(prompt_text) > 2500:
        confidence -= 15
        warnings.append("Prompt is quite long — consider trimming for token efficiency.")
    if "ignore" in prompt_text.lower() and "instructions" in prompt_text.lower():
        confidence -= 10
        warnings.append("Publishing warning: prompt references overriding instructions — double-check for contradictions.")
    if not any(w in prompt_text.lower() for w in ("if the user", "if they", "if a learner", "never", "do not")):
        guardrails.append("Add explicit guidance for off-topic, abusive, or unexpected learner input.")

    return {
        "quality_score": clamp(quality),
        "quality_breakdown": {},
        "quality_recommendations": recommendations[:5],
        "confidence_score": clamp(confidence),
        "confidence_explanation": "Offline heuristic estimate — connect Groq for a full evaluation.",
        "confidence_warnings": warnings[:5],
        "confidence_guardrail_suggestions": guardrails[:5],
        "_source": "offline",
    }


async def evaluate_template(scenario: Dict) -> Dict:
    if not llm_client.is_configured():
        return offline_evaluate_template(scenario)

    prompt = prompts.build_template_evaluation_prompt(scenario)
    try:
        raw = await llm_client.chat_json(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=700
        )
        return {
            "quality_score": clamp(raw.get("quality_score", 0)),
            "quality_breakdown": raw.get("quality_breakdown") or {},
            "quality_recommendations": clean_str_list(raw.get("quality_recommendations"), 5),
            "confidence_score": clamp(raw.get("confidence_score", 0)),
            "confidence_explanation": str(raw.get("confidence_explanation", "")).strip(),
            "confidence_warnings": clean_str_list(raw.get("confidence_warnings"), 5),
            "confidence_guardrail_suggestions": clean_str_list(raw.get("confidence_guardrail_suggestions"), 5),
            "_source": "llm",
        }
    except (llm_client.LLMError, TypeError, ValueError) as e:
        logger.warning("Groq template evaluation failed (%s); using offline evaluator", e)
        return offline_evaluate_template(scenario)


def assess_readiness(scenario: Dict, quality_score, confidence_score) -> Dict:
    """CM-US-07: pure deterministic checklist — prompt/vocab/category/difficulty/
    testing completion, plus a minimum bar on the (already-computed) quality and
    confidence scores. Never calls the LLM itself; the caller is responsible for
    running evaluate_template first if scores are missing."""
    checks = {
        "prompt": bool((scenario.get("system_prompt") or "").strip()),
        "vocabulary": len(scenario.get("target_vocab") or []) >= 3,
        "category": bool(scenario.get("category")),
        "difficulty": bool(scenario.get("difficulty")),
        "tested": bool(scenario.get("sandbox_tested")),
        "quality_score": quality_score is not None and quality_score >= QUALITY_CONFIDENCE_MIN_TO_PASS,
        "confidence_score": confidence_score is not None and confidence_score >= QUALITY_CONFIDENCE_MIN_TO_PASS,
    }
    missing = [name for name, passed in checks.items() if not passed]
    ready = not missing
    score = round(100 * sum(checks.values()) / len(checks))
    return {"ready": ready, "score": score, "checks": checks, "missing": missing}
