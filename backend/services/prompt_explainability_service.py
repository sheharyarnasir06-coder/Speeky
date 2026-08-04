"""
Content Management — Prompt Explainability Report (CM-US-11 / US-195).

Explains WHY a template received the quality/confidence scores it did.

The acceptance criterion is absolute: "Every deduction in scoring must include an
explanation." That is not left to the model's goodwill — `_reconcile_deductions`
checks the returned report against the actual score breakdown and synthesises an
entry for any sub-100 dimension the model failed to justify. An unexplained
deduction can therefore never reach the admin.

The three spec exception cases are all first-class outputs, not errors:
  * multiple overlapping issues -> `overlapping_issues` groups them so the admin
    sees one root cause instead of five symptoms.
  * minimal issues              -> `minimal_issues` true; the UI shows a clean
    bill of health instead of an empty, broken-looking panel.
  * AI uncertainty              -> `analysis_confidence` 0-100 plus `low_confidence`,
    so a shaky analysis is labelled rather than presented as fact. Named for
    CONFIDENCE, not uncertainty: an "uncertainty" field invites the model to
    return 20 meaning "barely uncertain", which inverts the whole signal.
"""

import logging
from typing import Dict, List, Optional

from lib.scoring import clamp, clean_str_list
from lib import llm_client, prompts

logger = logging.getLogger(__name__)

# A dimension at or above this is treated as "no deduction to explain".
FULL_MARKS_THRESHOLD = 100

# Below this the report itself is flagged as low-confidence (CM-US-11 exception:
# "AI uncertainty") so the admin weights it accordingly. This is the model's
# confidence in its OWN analysis: high = trustworthy.
ANALYSIS_CONFIDENCE_FLOOR = 50

# At or below this many findings the template is reported as "minimal issues"
# rather than padded out with invented problems.
MINIMAL_ISSUE_COUNT = 1

# Human-readable names for the quality breakdown keys produced by
# content_scoring_service / TEMPLATE_EVALUATION_PROMPT.
_DIMENSION_LABELS = {
    "prompt_completeness": "Prompt completeness",
    "persona_consistency": "Persona consistency",
    "scenario_clarity": "Scenario clarity",
    "vocabulary_relevance": "Vocabulary relevance",
    "learning_objective_alignment": "Learning objective alignment",
}


def _reconcile_deductions(model_deductions, breakdown: Dict) -> List[Dict]:
    """CM-US-11 acceptance enforcement.

    Every breakdown dimension scoring below full marks MUST come back with an
    explanation. The model is asked for this, but asking is not a guarantee — so
    any dimension it skipped gets a synthesised entry here. The result is that
    the acceptance criterion holds structurally rather than probabilistically.
    """
    explained: Dict[str, Dict] = {}
    for entry in model_deductions or []:
        if not isinstance(entry, dict):
            continue
        dimension = str(entry.get("dimension", "")).strip()
        explanation = str(entry.get("explanation", "")).strip()
        if not dimension or not explanation:
            continue
        explained[dimension] = {
            "dimension": dimension,
            "label": _DIMENSION_LABELS.get(dimension, dimension.replace("_", " ").capitalize()),
            "score": clamp(entry.get("score", breakdown.get(dimension, 0))),
            "points_lost": max(0, FULL_MARKS_THRESHOLD - clamp(entry.get("score", breakdown.get(dimension, 0)))),
            "explanation": explanation,
            "source": "ai",
        }

    for dimension, score in (breakdown or {}).items():
        value = clamp(score)
        if value >= FULL_MARKS_THRESHOLD or dimension in explained:
            continue
        label = _DIMENSION_LABELS.get(dimension, dimension.replace("_", " ").capitalize())
        explained[dimension] = {
            "dimension": dimension,
            "label": label,
            "score": value,
            "points_lost": FULL_MARKS_THRESHOLD - value,
            "explanation": (
                f"{label} scored {value}/100. The evaluator did not return a specific "
                "reason for this deduction — re-run the analysis, or review this "
                "dimension manually before publishing."
            ),
            "source": "synthesised",
        }

    return sorted(explained.values(), key=lambda d: d["points_lost"], reverse=True)


def _group_overlapping(weaknesses: List[str], ambiguous: List[Dict], missing: List[str]) -> List[Dict]:
    """CM-US-11 exception: multiple overlapping issues. Rather than showing three
    separate lists that all describe the same underlying gap, findings are grouped
    by theme so the admin sees the root cause once."""
    groups = []
    if ambiguous:
        groups.append({
            "theme": "Ambiguous instructions",
            "count": len(ambiguous),
            "detail": "Wording that the AI could read more than one way — the most common cause of persona drift.",
        })
    if missing:
        groups.append({
            "theme": "Missing constraints",
            "count": len(missing),
            "detail": "Behaviour the prompt leaves undefined, so the model decides for itself at runtime.",
        })
    if weaknesses:
        groups.append({
            "theme": "Content weaknesses",
            "count": len(weaknesses),
            "detail": "Substantive gaps in what the scenario asks the learner to practise.",
        })
    return groups


def offline_explain(scenario: Dict, quality_score, quality_breakdown, confidence_score) -> Dict:
    """Deterministic fallback. Cannot perform real language analysis, so it makes
    no claims it can't support — it reports the structural facts it can verify and
    marks itself low-confidence so nobody mistakes it for a real review."""
    prompt_text = scenario.get("system_prompt") or ""
    vocab = scenario.get("target_vocab") or []

    strengths: List[str] = []
    weaknesses: List[str] = []
    missing: List[str] = []

    if len(prompt_text) >= 400:
        strengths.append("The system prompt is substantial enough to establish a persona in detail.")
    if scenario.get("opening_line"):
        strengths.append("An explicit opening line makes the scenario start predictably.")
    if len(vocab) >= 6:
        strengths.append(f"{len(vocab)} target words give the learner plenty to practise toward.")

    if len(prompt_text) < 150:
        weaknesses.append("The system prompt is very short — the AI has little to anchor its persona to.")
    if not any(marker in prompt_text.lower() for marker in ("never", "do not", "don't", "avoid")):
        missing.append("No explicit prohibitions — add what the AI must never do or say.")
    if not any(marker in prompt_text.lower() for marker in ("if the user", "if they", "if a learner")):
        missing.append("No conditional handling for off-topic, abusive, or unexpected learner input.")

    deductions = _reconcile_deductions([], quality_breakdown or {})
    finding_count = len(weaknesses) + len(missing)

    return {
        "summary": (
            "Offline structural review only — connect Groq for a full language analysis. "
            f"Quality scored {quality_score if quality_score is not None else 'not yet'}."
        ),
        "strengths": strengths or ["No structural strengths detected offline."],
        "weaknesses": weaknesses,
        "ambiguous_wording": [],
        "missing_constraints": missing,
        "suggested_improvements": [
            "Re-run this analysis with Groq configured for wording-level findings.",
        ],
        "deductions": deductions,
        "overlapping_issues": _group_overlapping(weaknesses, [], missing),
        "minimal_issues": finding_count <= MINIMAL_ISSUE_COUNT,
        "analysis_confidence": 30,
        "low_confidence": True,
        "quality_score": quality_score,
        "confidence_score": confidence_score,
        "_source": "offline",
    }


async def explain(scenario: Dict, quality_score, quality_breakdown: Optional[Dict], confidence_score) -> Dict:
    """CM-US-11 happy path: the admin selects "View Analysis"."""
    breakdown = quality_breakdown or {}

    if not llm_client.is_configured():
        return offline_explain(scenario, quality_score, breakdown, confidence_score)

    prompt = prompts.build_prompt_explainability_prompt(
        scenario, quality_score, breakdown, confidence_score
    )
    try:
        raw = await llm_client.chat_json(
            [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1200
        )

        ambiguous = []
        for entry in raw.get("ambiguous_wording") or []:
            if isinstance(entry, dict) and str(entry.get("phrase", "")).strip():
                ambiguous.append({
                    "phrase": str(entry["phrase"]).strip(),
                    "why": str(entry.get("why", "")).strip() or "Open to more than one reading.",
                })
            elif isinstance(entry, str) and entry.strip():
                # Model returned a bare string instead of the documented object.
                ambiguous.append({"phrase": entry.strip(), "why": "Open to more than one reading."})

        weaknesses = clean_str_list(raw.get("weaknesses"), 8)
        missing = clean_str_list(raw.get("missing_constraints"), 8)
        analysis_confidence = clamp(raw.get("analysis_confidence", 70))
        finding_count = len(weaknesses) + len(missing) + len(ambiguous)

        return {
            "summary": str(raw.get("summary", "")).strip() or "No summary returned.",
            "strengths": clean_str_list(raw.get("strengths"), 8),
            "weaknesses": weaknesses,
            "ambiguous_wording": ambiguous[:8],
            "missing_constraints": missing,
            "suggested_improvements": clean_str_list(raw.get("suggested_improvements"), 8),
            "deductions": _reconcile_deductions(raw.get("deductions"), breakdown),
            "overlapping_issues": _group_overlapping(weaknesses, ambiguous, missing),
            "minimal_issues": finding_count <= MINIMAL_ISSUE_COUNT,
            "analysis_confidence": analysis_confidence,
            "low_confidence": analysis_confidence < ANALYSIS_CONFIDENCE_FLOOR,
            "quality_score": quality_score,
            "confidence_score": confidence_score,
            "_source": "llm",
        }
    except (llm_client.LLMError, TypeError, ValueError) as e:
        logger.warning("Groq explainability report failed (%s); using offline explainer", e)
        return offline_explain(scenario, quality_score, breakdown, confidence_score)
