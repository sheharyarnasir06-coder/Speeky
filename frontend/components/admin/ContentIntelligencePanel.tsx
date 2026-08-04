"use client";

import * as React from "react";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  CheckCircle2,
  History,
  Info,
  Loader2,
  Rocket,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  adminDeploymentConfidence,
  adminDeploymentHistory,
  adminExplainPrompt,
  adminGetExplanation,
  adminGetVocabCoverage,
  adminPerformanceDetail,
  adminScoreVocabCoverage,
  type CustomScenario,
  type DeploymentConfidence,
  type DeploymentRecord,
  type ExplainabilityReport,
  type TemplateMetrics,
  type VocabCoverageFlag,
  type VocabCoverageResult,
} from "@/lib/scenario";
import { cn } from "@/lib/utils";

/**
 * Sprint 3 content intelligence for a single template.
 *
 * US-192 Vocabulary Coverage · US-193 Performance · US-195 Explainability ·
 * US-198 Deployment Confidence.
 *
 * Each tab loads its CACHED result on open and only calls the LLM when the admin
 * explicitly clicks the recompute button, so browsing templates never triggers
 * AI spend. Tabs also load lazily — opening the panel fetches one tab, not four.
 */

type TabId = "coverage" | "performance" | "explain" | "deployment";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "coverage", label: "Vocabulary", icon: BookOpen },
  { id: "performance", label: "Performance", icon: BarChart3 },
  { id: "explain", label: "Analysis", icon: Sparkles },
  { id: "deployment", label: "Deployment", icon: Rocket },
];

/** CM-US-08 exception flags rendered as plain language for the admin. */
const FLAG_COPY: Record<VocabCoverageFlag, string> = {
  excessive_repetition: "Several words teach the same thing",
  vocabulary_gaps: "Essential vocabulary is missing",
  incorrect_difficulty: "List doesn't match the declared difficulty",
  domain_mismatch: "Some words belong to a different domain",
};

function scoreTone(score: number | null | undefined) {
  if (score === null || score === undefined) return "neutral" as const;
  if (score >= 70) return "success" as const;
  if (score >= 50) return "warning" as const;
  return "danger" as const;
}

/** null means "no data", which must never render as 0. */
function metric(value: number | null | undefined, suffix = "") {
  return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-44 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-normal ease-out-expo",
            value >= 70 ? "bg-success" : value >= 50 ? "bg-warning" : "bg-danger",
          )}
          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        />
      </div>
      <span className="w-9 shrink-0 text-right text-xs font-medium tabular-nums text-foreground">
        {value}
      </span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted-foreground">{children}</p>;
}

function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      Loading…
    </div>
  );
}

export function ContentIntelligencePanel({ scenario }: { scenario: CustomScenario }) {
  const [tab, setTab] = React.useState<TabId>("coverage");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [coverage, setCoverage] = React.useState<VocabCoverageResult | null>(null);
  const [coverageLoaded, setCoverageLoaded] = React.useState(false);
  const [performance, setPerformance] = React.useState<TemplateMetrics | null>(null);
  const [report, setReport] = React.useState<ExplainabilityReport | null>(null);
  const [reportLoaded, setReportLoaded] = React.useState(false);
  const [deployment, setDeployment] = React.useState<DeploymentConfidence | null>(null);
  const [history, setHistory] = React.useState<DeploymentRecord[]>([]);
  const [loadedTabs, setLoadedTabs] = React.useState<Set<TabId>>(new Set());

  const id = scenario.id;

  // Reset everything when the admin switches to a different template, otherwise
  // the previous template's scores would briefly render under the new title.
  React.useEffect(() => {
    setCoverage(null);
    setCoverageLoaded(false);
    setPerformance(null);
    setReport(null);
    setReportLoaded(false);
    setDeployment(null);
    setHistory([]);
    setLoadedTabs(new Set());
    setError(null);
  }, [id]);

  // Lazy per-tab load of the CACHED result — no LLM call, so switching tabs is cheap.
  React.useEffect(() => {
    if (loadedTabs.has(tab)) return;
    let cancelled = false;

    (async () => {
      setBusy(true);
      setError(null);
      try {
        if (tab === "coverage") {
          const res = await adminGetVocabCoverage(id);
          if (cancelled) return;
          if (res.feedback && res.coverage_score !== null) {
            setCoverage({
              scenario_id: id,
              coverage_score: res.coverage_score,
              ...res.feedback,
            } as VocabCoverageResult);
          }
          setCoverageLoaded(true);
        } else if (tab === "performance") {
          const res = await adminPerformanceDetail(id);
          if (!cancelled) setPerformance(res.metrics);
        } else if (tab === "explain") {
          const res = await adminGetExplanation(id);
          if (!cancelled) {
            setReport(res.report);
            setReportLoaded(true);
          }
        } else {
          const res = await adminDeploymentHistory(id);
          if (!cancelled) setHistory(res.deployments);
        }
        if (!cancelled) setLoadedTabs((prev) => new Set(prev).add(tab));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load this section.");
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [tab, id, loadedTabs]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center gap-2" role="tablist" aria-label="Content intelligence">
        {TABS.map(({ id: tabId, label, icon: Icon }) => (
          <button
            key={tabId}
            type="button"
            role="tab"
            aria-selected={tab === tabId}
            onClick={() => setTab(tabId)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors duration-fast",
              tab === tabId
                ? "border-primary bg-secondary text-primary"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <p role="alert" className="mb-3 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {busy && !coverage && !performance && !report && !deployment ? <Loading /> : null}

      {/* ── US-192 Vocabulary Coverage Score ───────────────────────────── */}
      {tab === "coverage" ? (
        <section aria-label="Vocabulary coverage">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">Vocabulary Coverage Score</h3>
              {coverage ? (
                <Badge tone={scoreTone(coverage.coverage_score)}>{coverage.coverage_score}/100</Badge>
              ) : null}
            </div>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => run(async () => setCoverage(await adminScoreVocabCoverage(id)))}
            >
              {coverage ? "Re-score" : "Score coverage"}
            </Button>
          </div>

          {!coverage && coverageLoaded && !busy ? (
            <Empty>Not scored yet — run a coverage check to see how well the word list covers this objective.</Empty>
          ) : null}

          {coverage ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <ScoreBar label="Topic relevance" value={coverage.breakdown.topic_relevance} />
                <ScoreBar label="Difficulty distribution" value={coverage.breakdown.difficulty_distribution} />
                <ScoreBar label="Low redundancy" value={coverage.breakdown.redundancy} />
                <ScoreBar label="Coverage completeness" value={coverage.breakdown.coverage_completeness} />
              </div>

              {coverage.flags.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {coverage.flags.map((flag) => (
                    <Badge key={flag} tone="warning" dot>
                      {FLAG_COPY[flag] ?? flag}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Recommendations
                </p>
                <ul className="flex flex-col gap-1.5">
                  {coverage.recommendations.map((rec) => (
                    <li key={rec} className="flex gap-2 text-sm text-foreground">
                      <span aria-hidden="true" className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                      {rec}
                    </li>
                  ))}
                </ul>
              </div>

              {coverage.redundant_words.length ? (
                <p className="text-xs text-muted-foreground">
                  Possible duplicates: {coverage.redundant_words.join(", ")}
                </p>
              ) : null}
              {coverage.suggested_additions.length ? (
                <p className="text-xs text-muted-foreground">
                  Suggested additions: {coverage.suggested_additions.join(", ")}
                </p>
              ) : null}
              {coverage._source === "offline" ? (
                <p className="text-xs text-warning">{coverage._note}</p>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ── US-193 Template Performance ────────────────────────────────── */}
      {tab === "performance" ? (
        <section aria-label="Template performance">
          <h3 className="mb-3 text-sm font-semibold text-foreground">Performance</h3>
          {performance ? (
            performance.no_analytics ? (
              <Empty>
                {performance.newly_published
                  ? "Newly published — no learner sessions yet. Metrics appear once learners start practising."
                  : "No analytics available for this template yet."}
              </Empty>
            ) : (
              <div className="flex flex-col gap-3">
                {performance.insufficient_data ? (
                  <p role="status" className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-foreground">
                    Only {performance.sample_size} session(s) so far — treat these figures as provisional.
                  </p>
                ) : null}
                {performance.archived ? (
                  <p role="status" className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                    This template is archived — these numbers are historical and no longer changing.
                  </p>
                ) : null}
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {[
                    ["Usage", metric(performance.usage_count)],
                    ["Completion", metric(performance.completion_rate, "%")],
                    ["Avg. learner score", metric(performance.average_learner_score)],
                    ["Confidence change", performance.confidence_improvement === null
                      ? "—"
                      : `${performance.confidence_improvement > 0 ? "+" : ""}${performance.confidence_improvement}`],
                    ["Vocabulary success", metric(performance.vocabulary_success_rate, "%")],
                    ["Abandonment", metric(performance.session_abandonment, "%")],
                    ["Satisfaction", performance.learner_satisfaction === null
                      ? "—"
                      : `${performance.learner_satisfaction}/5`],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl border border-border bg-surface p-3">
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className="mt-0.5 text-lg font-semibold tabular-nums text-foreground">{value}</dd>
                    </div>
                  ))}
                </dl>
                {performance.learner_satisfaction === null ? (
                  <p className="text-xs text-muted-foreground">
                    No learners have rated this scenario yet — rating is always optional.
                  </p>
                ) : null}
              </div>
            )
          ) : busy ? null : (
            <Empty>No performance data.</Empty>
          )}
        </section>
      ) : null}

      {/* ── US-195 Prompt Explainability Report ────────────────────────── */}
      {tab === "explain" ? (
        <section aria-label="Prompt explainability">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground">Prompt Explainability</h3>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => run(async () => setReport(await adminExplainPrompt(id)))}
            >
              {report ? "Re-run analysis" : "View analysis"}
            </Button>
          </div>

          {!report && reportLoaded && !busy ? (
            <Empty>No analysis yet — run one to see exactly why this template scored the way it did.</Empty>
          ) : null}

          {report ? (
            <div className="flex flex-col gap-4">
              {report.low_confidence ? (
                <p role="status" className="flex items-start gap-2 rounded-lg bg-warning/10 px-3 py-2 text-xs text-foreground">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                  The evaluator rated its own certainty at {report.analysis_confidence}/100 — treat this
                  analysis as indicative rather than definitive.
                </p>
              ) : null}

              <p className="text-sm text-foreground">{report.summary}</p>

              {report.minimal_issues ? (
                <p className="flex items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-sm text-foreground">
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                  Minimal issues found — this template is in good shape.
                </p>
              ) : null}

              {report.overlapping_issues.length > 1 ? (
                <div className="rounded-xl border border-border bg-surface p-3">
                  <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-foreground">
                    <Info className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                    Related findings grouped
                  </p>
                  <ul className="flex flex-col gap-1">
                    {report.overlapping_issues.map((group) => (
                      <li key={group.theme} className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">
                          {group.theme} ({group.count})
                        </span>{" "}
                        — {group.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {report.deductions.length ? (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Why points were deducted
                  </p>
                  <ul className="flex flex-col gap-2">
                    {report.deductions.map((d) => (
                      <li key={d.dimension} className="rounded-xl border border-border bg-surface p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium text-foreground">{d.label}</span>
                          <Badge tone={scoreTone(d.score)}>−{d.points_lost}</Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">{d.explanation}</p>
                        {d.source === "synthesised" ? (
                          <p className="mt-1 text-xs text-warning">
                            The evaluator did not justify this one — re-run the analysis for detail.
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {([
                ["Strengths", report.strengths],
                ["Weaknesses", report.weaknesses],
                ["Missing constraints", report.missing_constraints],
                ["Suggested improvements", report.suggested_improvements],
              ] as const).map(([label, items]) =>
                items.length ? (
                  <div key={label}>
                    <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {label}
                    </p>
                    <ul className="flex flex-col gap-1">
                      {items.map((item) => (
                        <li key={item} className="flex gap-2 text-sm text-foreground">
                          <span aria-hidden="true" className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null,
              )}

              {report.ambiguous_wording.length ? (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Ambiguous wording
                  </p>
                  <ul className="flex flex-col gap-1.5">
                    {report.ambiguous_wording.map((a) => (
                      <li key={a.phrase} className="rounded-lg bg-muted px-3 py-2 text-xs">
                        <span className="font-medium text-foreground">&ldquo;{a.phrase}&rdquo;</span>
                        <span className="text-muted-foreground"> — {a.why}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ── US-198 Deployment Confidence ───────────────────────────────── */}
      {tab === "deployment" ? (
        <section aria-label="Deployment confidence">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">Deployment Confidence</h3>
              {deployment ? (
                <Badge tone={scoreTone(deployment.confidence_score)}>
                  {deployment.confidence_score}/100
                </Badge>
              ) : null}
            </div>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() =>
                run(async () => {
                  setDeployment(await adminDeploymentConfidence(id));
                  setHistory((await adminDeploymentHistory(id)).deployments);
                })
              }
            >
              {deployment ? "Re-evaluate" : "Evaluate"}
            </Button>
          </div>

          {deployment ? (
            <div className="flex flex-col gap-4">
              <p
                role={deployment.can_deploy ? "status" : "alert"}
                className={cn(
                  "rounded-lg px-3 py-2 text-sm",
                  deployment.can_deploy
                    ? deployment.requires_review
                      ? "bg-warning/10 text-foreground"
                      : "bg-success/10 text-foreground"
                    : "bg-danger/10 text-foreground",
                )}
              >
                {deployment.recommendation}
              </p>

              <div className="flex flex-col gap-2">
                <ScoreBar label="Prompt stability" value={deployment.breakdown.prompt_stability} />
                <ScoreBar label="Persona consistency" value={deployment.breakdown.persona_consistency} />
                <ScoreBar label="Vocabulary coverage" value={deployment.breakdown.vocabulary_coverage} />
                <ScoreBar label="Expected AI behaviour" value={deployment.breakdown.expected_ai_behavior} />
                <ScoreBar label="Sandbox success rate" value={deployment.breakdown.sandbox_success_rate} />
                <ScoreBar label="Deployment history" value={deployment.breakdown.deployment_history} />
              </div>

              <p className="text-xs text-muted-foreground">
                {deployment.sandbox_passes}/{deployment.sandbox_runs} sandbox runs passed ·{" "}
                {deployment.previous_deployments} previous deployment(s)
              </p>

              {[...deployment.blocking, ...deployment.warnings].length ? (
                <ul className="flex flex-col gap-2">
                  {deployment.blocking.map((x) => (
                    <li key={x.code} className="rounded-xl border border-danger/40 bg-danger/5 p-3">
                      <p className="text-sm font-medium text-foreground">
                        {x.code} · {x.title}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{x.detail}</p>
                      <p className="mt-1 text-xs text-foreground">{x.resolution}</p>
                    </li>
                  ))}
                  {deployment.warnings.map((x) => (
                    <li key={x.code} className="rounded-xl border border-warning/40 bg-warning/5 p-3">
                      <p className="text-sm font-medium text-foreground">
                        {x.code} · {x.title}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{x.detail}</p>
                      <p className="mt-1 text-xs text-foreground">{x.resolution}</p>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {history.length ? (
            <div className="mt-4">
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <History className="h-3.5 w-3.5" aria-hidden="true" />
                Deployment history
              </p>
              <ul className="flex flex-col gap-1">
                {history.slice(0, 8).map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-2 rounded-lg bg-surface px-3 py-1.5 text-xs">
                    <span className="text-foreground">
                      v{d.version} · {d.note || d.outcome}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="tabular-nums text-muted-foreground">{d.confidence_score}/100</span>
                      <span className="text-muted-foreground">
                        {new Date(d.created_at).toLocaleDateString()}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : !deployment && !busy ? (
            <Empty>No deployments recorded yet.</Empty>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
