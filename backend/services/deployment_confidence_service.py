"""
Content Management — Template Reliability & Deployment Confidence Monitoring
(CM-US-14 / US-198).

Produces a Deployment Confidence Score BEFORE a template goes live, from the six
inputs the spec names:

    prompt stability · persona consistency · vocabulary coverage
    expected AI behaviour · sandbox success rate · previous deployment history

and keeps monitoring AFTER deployment by folding live drift/performance back in.

This is deliberately a *composition* layer, not a new evaluator: prompt stability
and persona consistency already come out of content_scoring_service, vocabulary
coverage out of vocab_coverage_service, and post-deployment health out of
content_drift_service. Re-deriving any of them here would mean two sources of
truth for the same judgement.

Exception handling (all six from the spec) is expressed as two separate lists:
  * `blocking`  — hard stops. E-02 (sandbox failure) is the only true blocker;
                  a deployment cannot proceed while one is present.
  * `warnings`  — E-01/E-03/E-04/E-05/E-06 surface here with a recommendation,
                  because the spec's resolution for each is "warn / recommend
                  rollback / flag for revalidation", not "refuse".
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from prisma import Json

from lib.scoring import clamp
from lib.prisma_client import db

logger = logging.getLogger(__name__)

# Below this, CM-US-14 acceptance requires administrator review before
# publication — the publish gate returns it as an acknowledgeable warning.
LOW_CONFIDENCE_THRESHOLD = 60

# Weightings for the six named inputs. They sum to 1.0. Sandbox success and
# prompt stability carry the most weight because they are the two signals that
# most directly predict a template misbehaving in front of a learner.
_WEIGHTS = {
    "prompt_stability": 0.25,
    "persona_consistency": 0.20,
    "vocabulary_coverage": 0.15,
    "expected_ai_behavior": 0.15,
    "sandbox_success_rate": 0.15,
    "deployment_history": 0.10,
}

# A template with no sandbox runs at all scores this for sandbox success —
# neutral-low, not zero: "never tested" is worse than "tested and passed" but is
# not the same as "tested and failed".
_UNTESTED_SANDBOX_SCORE = 40

# With no prior deployments there is no history to judge; neutral rather than
# penalising a template for being new (CM-US-09's "newly published" logic).
_NO_HISTORY_SCORE = 70

# A confidence drop this large versus the last deployment is treated as a prompt
# regression (E-03).
_REGRESSION_DROP = 15


def compute_breakdown(
    quality_breakdown: Optional[Dict],
    confidence_score: Optional[int],
    vocab_coverage_score: Optional[int],
    sandbox_runs: int,
    sandbox_passes: int,
    previous_deployments: List,
) -> Dict:
    """Pure scoring of the six inputs — no DB, no LLM, fully unit-testable."""
    breakdown_source = quality_breakdown or {}

    # Prompt stability and expected AI behaviour both come from the confidence
    # evaluation (that is precisely what it measures); persona consistency has its
    # own dimension in the quality breakdown.
    prompt_stability = clamp(confidence_score if confidence_score is not None else 50)
    persona_consistency = clamp(breakdown_source.get("persona_consistency", 50))
    expected_ai_behavior = clamp(
        breakdown_source.get("learning_objective_alignment", breakdown_source.get("scenario_clarity", 50))
    )
    vocabulary_coverage = clamp(vocab_coverage_score if vocab_coverage_score is not None else 50)

    if sandbox_runs <= 0:
        sandbox_success_rate = _UNTESTED_SANDBOX_SCORE
    else:
        sandbox_success_rate = clamp(100 * sandbox_passes / sandbox_runs)

    if not previous_deployments:
        deployment_history = _NO_HISTORY_SCORE
    else:
        # Mean confidence of prior DEPLOYED attempts, penalised for any that were
        # blocked or rolled back.
        deployed = [d for d in previous_deployments if d.outcome == "DEPLOYED"]
        failed = [d for d in previous_deployments if d.outcome in ("BLOCKED", "ROLLED_BACK")]
        base = sum(d.confidenceScore for d in deployed) / len(deployed) if deployed else 50
        deployment_history = clamp(base - 10 * len(failed))

    return {
        "prompt_stability": prompt_stability,
        "persona_consistency": persona_consistency,
        "vocabulary_coverage": vocabulary_coverage,
        "expected_ai_behavior": expected_ai_behavior,
        "sandbox_success_rate": sandbox_success_rate,
        "deployment_history": deployment_history,
    }


def score_from_breakdown(breakdown: Dict) -> int:
    return clamp(sum(breakdown[key] * weight for key, weight in _WEIGHTS.items()))


def build_exceptions(
    breakdown: Dict,
    score: int,
    sandbox_runs: int,
    sandbox_passes: int,
    previous_deployments: List,
    model_changed: bool = False,
) -> Dict:
    """Maps the computed state onto CM-US-14's six documented exception cases."""
    blocking: List[Dict] = []
    warnings: List[Dict] = []

    # E-02: Sandbox Failure -> deployment blocked until testing passes.
    if sandbox_runs > 0 and sandbox_passes == 0:
        blocking.append({
            "code": "E-02",
            "title": "Sandbox failure",
            "detail": f"All {sandbox_runs} sandbox run(s) failed. Deployment is blocked until a test passes.",
            "resolution": "Fix the prompt and re-run the sandbox tester until it succeeds.",
        })
    elif sandbox_runs == 0:
        blocking.append({
            "code": "E-02",
            "title": "Never sandbox-tested",
            "detail": "This template has never been run through the sandbox tester.",
            "resolution": "Run the sandbox tester at least once before deploying.",
        })

    # E-01: Low Deployment Confidence -> warning + recommended improvements.
    if score < LOW_CONFIDENCE_THRESHOLD:
        weakest = sorted(breakdown.items(), key=lambda kv: kv[1])[:2]
        warnings.append({
            "code": "E-01",
            "title": "Low deployment confidence",
            "detail": f"Scored {score}/100, below the {LOW_CONFIDENCE_THRESHOLD} review threshold.",
            "resolution": "Strongest gains available in: "
                          + ", ".join(k.replace("_", " ") for k, _ in weakest) + ".",
        })

    # E-03: Prompt Regression -> recommend rollback to previous stable version.
    deployed = [d for d in previous_deployments if d.outcome == "DEPLOYED"]
    if deployed:
        last = max(deployed, key=lambda d: d.createdAt)
        if last.confidenceScore - score >= _REGRESSION_DROP:
            warnings.append({
                "code": "E-03",
                "title": "Prompt regression",
                "detail": f"Confidence fell from {last.confidenceScore} to {score} since version {last.version}.",
                "resolution": f"Consider rolling back to version {last.version}, which scored higher.",
            })

    # E-06: Inconsistent Persona Behavior -> reduce score, recommend refinement.
    if breakdown["persona_consistency"] < 50:
        warnings.append({
            "code": "E-06",
            "title": "Inconsistent persona behaviour",
            "detail": f"Persona consistency scored {breakdown['persona_consistency']}/100.",
            "resolution": "Tighten the persona description so the AI has less room to drift out of character.",
        })

    # E-05: AI Model Update Changes Behavior -> flag for revalidation.
    if model_changed:
        warnings.append({
            "code": "E-05",
            "title": "AI model changed since last evaluation",
            "detail": "The scores on record were produced by a different model version.",
            "resolution": "Re-run evaluation and the sandbox tester to revalidate this template.",
        })

    return {"blocking": blocking, "warnings": warnings}


def _effective_sandbox_counts(scenario) -> tuple:
    """Backward compatibility for templates published before the sandbox counters
    existed.

    `sandboxRuns`/`sandboxPasses` default to 0 on every pre-existing row, but
    those templates *did* clear the CM-US-01 sandbox gate — `sandboxTested` is
    True precisely because the admin ran the tester successfully. Reading the raw
    counters would report "never sandbox-tested" and block every already-live
    scenario, which is a regression, not a finding. Treat the legacy flag as the
    one passing run it represents.
    """
    if scenario.sandboxRuns > 0:
        return scenario.sandboxRuns, scenario.sandboxPasses
    if scenario.sandboxTested:
        return 1, 1
    return 0, 0


async def evaluate(scenario_id: str, model_changed: bool = False) -> Optional[Dict]:
    """Full pre-deployment evaluation for one scenario."""
    scenario = await db.customscenario.find_unique(where={"id": scenario_id})
    if not scenario:
        return None

    previous = await db.templatedeployment.find_many(
        where={"scenarioId": scenario_id}, order={"createdAt": "desc"}, take=20
    )
    quality_breakdown = ((scenario.qualityFeedback or {}).get("breakdown")) or {}
    runs, passes = _effective_sandbox_counts(scenario)

    breakdown = compute_breakdown(
        quality_breakdown,
        scenario.confidenceScore,
        scenario.vocabCoverageScore,
        runs,
        passes,
        previous,
    )
    score = score_from_breakdown(breakdown)
    exceptions = build_exceptions(
        breakdown, score, runs, passes, previous, model_changed
    )

    recommendation = (
        "Blocked — resolve the issues below before deploying." if exceptions["blocking"]
        else "Requires administrator review before publication." if score < LOW_CONFIDENCE_THRESHOLD
        else "Cleared for deployment."
    )

    result = {
        "scenario_id": scenario_id,
        "version": scenario.version,
        "confidence_score": score,
        "breakdown": breakdown,
        "blocking": exceptions["blocking"],
        "warnings": exceptions["warnings"],
        "recommendation": recommendation,
        "requires_review": score < LOW_CONFIDENCE_THRESHOLD,
        "can_deploy": not exceptions["blocking"],
        "sandbox_runs": scenario.sandboxRuns,
        "sandbox_passes": scenario.sandboxPasses,
        "previous_deployments": len(previous),
    }

    await db.customscenario.update(
        where={"id": scenario_id},
        data={
            "deploymentConfidence": score,
            "deploymentFeedback": Json({
                "breakdown": breakdown,
                "blocking": exceptions["blocking"],
                "warnings": exceptions["warnings"],
                "recommendation": recommendation,
            }),
            "deploymentScoredAt": datetime.now(timezone.utc),
        },
    )
    return result


async def record_deployment(scenario_id: str, version: int, score: int, breakdown: Dict,
                            outcome: str = "DEPLOYED", note: str = "") -> None:
    """Append to deployment history — the input to the NEXT confidence score, and
    the record E-03 compares against to spot a regression."""
    await db.templatedeployment.create(
        data={
            "scenarioId": scenario_id,
            "version": version,
            "confidenceScore": score,
            "breakdown": Json(breakdown),
            "outcome": outcome,
            "note": note,
        }
    )


async def deployment_history(scenario_id: str) -> List[Dict]:
    rows = await db.templatedeployment.find_many(
        where={"scenarioId": scenario_id}, order={"createdAt": "desc"}, take=50
    )
    return [
        {
            "id": r.id,
            "version": r.version,
            "confidence_score": r.confidenceScore,
            "breakdown": r.breakdown,
            "outcome": r.outcome,
            "note": r.note,
            "created_at": r.createdAt.isoformat(),
        }
        for r in rows
    ]


async def record_sandbox_run(scenario_id: str, passed: bool) -> None:
    """CM-US-14 input: sandbox success rate. Counters are cumulative and are
    never reset by an edit, so the rate reflects the template's whole testing
    history rather than just the current editing session."""
    await db.customscenario.update(
        where={"id": scenario_id},
        data={
            "sandboxRuns": {"increment": 1},
            "sandboxPasses": {"increment": 1 if passed else 0},
        },
    )
