"use client";

import * as React from "react";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  BellRing,
  CheckCircle2,
  Loader2,
  ShieldAlert,
  TrendingDown,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import {
  adminAcknowledgeDriftAlert,
  adminDriftOverview,
  adminPerformanceOverview,
  type DriftAlert,
  type DriftAnalysis,
  type TemplatePerformanceRow,
} from "@/lib/scenario";
import { cn } from "@/lib/utils";

/**
 * Content Intelligence dashboard — the catalogue-wide views.
 *
 * US-193 Template Performance Dashboard · US-196 Content Drift Detection.
 *
 * Per-template detail lives on the Custom Scenarios page next to the template it
 * describes; this page answers "how is the whole catalogue doing".
 *
 * Opening this page runs drift detection, because this repo has no scheduler —
 * the same opportunistic pattern scenario_service already uses to purge archives.
 */

const SEVERITY_TONE = {
  CRITICAL: "danger",
  WARNING: "warning",
  INFO: "neutral",
} as const;

/** null means "no data" — it must never render as 0. */
function metric(value: number | null | undefined, suffix = "") {
  return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

export default function ContentIntelligencePage() {
  const { user, isLoading } = useAuth();
  const [templates, setTemplates] = React.useState<TemplatePerformanceRow[]>([]);
  const [analyses, setAnalyses] = React.useState<DriftAnalysis[]>([]);
  const [alerts, setAlerts] = React.useState<DriftAlert[]>([]);
  const [platformWide, setPlatformWide] = React.useState<string[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [acking, setAcking] = React.useState<string | null>(null);

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  React.useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    (async () => {
      try {
        // Both are independent reads — run them together rather than sequentially.
        const [perf, drift] = await Promise.all([
          adminPerformanceOverview(),
          adminDriftOverview(),
        ]);
        if (cancelled) return;
        setTemplates(perf.templates);
        setAnalyses(drift.analyses);
        setAlerts(drift.alerts);
        setPlatformWide(drift.platform_wide_signals);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load content intelligence.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  async function acknowledge(alertId: string) {
    setAcking(alertId);
    try {
      await adminAcknowledgeDriftAlert(alertId);
      setAlerts((prev) =>
        prev.map((a) => (a.id === alertId ? { ...a, status: "ACKNOWLEDGED" as const } : a)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not acknowledge that alert.");
    } finally {
      setAcking(null);
    }
  }

  if (isLoading) return null;

  if (!isAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Admin access required.</p>
      </div>
    );
  }

  const openAlerts = alerts.filter((a) => a.status === "OPEN");

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link
          href="/dashboard/admin"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors duration-fast hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Admin
        </Link>
        <h1 className="mt-3 font-serif text-h1 font-semibold text-foreground">
          Content Intelligence
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          How published templates are actually performing for learners, and which ones have
          started drifting from the results they used to get.
        </p>
      </div>

      {error ? (
        <p role="alert" className="rounded-lg bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Analysing the catalogue…
        </div>
      ) : (
        <>
          {/* ── US-196 Drift alerts ─────────────────────────────────────── */}
          <section aria-labelledby="drift-heading" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="drift-heading" className="text-h3 font-semibold text-foreground">
                Drift alerts
              </h2>
              {openAlerts.length ? (
                <Badge tone="danger" dot>
                  {openAlerts.length} open
                </Badge>
              ) : null}
            </div>

            {platformWide.length ? (
              <p role="status" className="rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Platform-wide change detected.</span>{" "}
                {platformWide.length} signal(s) degraded across most of the catalogue at once, which
                points at a model or platform change rather than any single template. Per-template
                alerts for those signals are suppressed.
              </p>
            ) : null}

            {alerts.length === 0 ? (
              <p className="flex items-center gap-2 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                No drift detected. Every template with enough data is performing in line with its
                own baseline.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {alerts.map((alert) => (
                  <li
                    key={alert.id}
                    className={cn(
                      "rounded-2xl border p-4",
                      alert.status === "ACKNOWLEDGED"
                        ? "border-border bg-surface opacity-80"
                        : "border-danger/30 bg-danger/5",
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={SEVERITY_TONE[alert.severity]}>{alert.severity}</Badge>
                          {alert.status === "ACKNOWLEDGED" ? (
                            <Badge tone="neutral">Acknowledged</Badge>
                          ) : null}
                          <span className="text-xs text-muted-foreground">
                            {new Date(alert.detected_at).toLocaleString()}
                          </span>
                        </div>
                        <p className="mt-1.5 text-sm text-foreground">{alert.summary}</p>
                      </div>
                      {alert.status === "OPEN" ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={acking === alert.id}
                          onClick={() => acknowledge(alert.id)}
                        >
                          Acknowledge
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── US-193 Template performance ─────────────────────────────── */}
          <section aria-labelledby="perf-heading" className="flex flex-col gap-3">
            <h2 id="perf-heading" className="text-h3 font-semibold text-foreground">
              Template performance
            </h2>

            {templates.length === 0 ? (
              <p className="rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted-foreground">
                No custom templates yet. Publish one from Custom Scenarios to start collecting
                performance data.
              </p>
            ) : (
              // Wide table must scroll inside its own container so the page body
              // never scrolls horizontally on a phone.
              <div className="overflow-x-auto rounded-2xl border border-border bg-surface-elevated">
                <table className="w-full min-w-[52rem] text-left text-sm">
                  <caption className="sr-only">
                    Learner outcomes and engagement for every custom template
                  </caption>
                  <thead className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th scope="col" className="px-4 py-3 font-medium">Template</th>
                      <th scope="col" className="px-4 py-3 font-medium">Uses</th>
                      <th scope="col" className="px-4 py-3 font-medium">Completion</th>
                      <th scope="col" className="px-4 py-3 font-medium">Avg. score</th>
                      <th scope="col" className="px-4 py-3 font-medium">Confidence</th>
                      <th scope="col" className="px-4 py-3 font-medium">Vocabulary</th>
                      <th scope="col" className="px-4 py-3 font-medium">Abandon</th>
                      <th scope="col" className="px-4 py-3 font-medium">Satisfaction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {templates.map((row) => {
                      const m = row.metrics;
                      const drift = analyses.find((a) => a.scenario_id === row.scenario_id);
                      return (
                        <tr key={row.scenario_id} className="border-b border-border last:border-0">
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-medium text-foreground">{row.title}</span>
                              {row.status === "ARCHIVED" ? <Badge tone="neutral">Archived</Badge> : null}
                              {m.newly_published ? <Badge tone="accent">New</Badge> : null}
                              {m.insufficient_data && !m.no_analytics ? (
                                <Badge tone="warning">Provisional</Badge>
                              ) : null}
                              {drift?.severity ? (
                                <Badge tone={SEVERITY_TONE[drift.severity]} dot>
                                  Drift
                                </Badge>
                              ) : null}
                            </div>
                            <span className="text-xs text-muted-foreground">{row.category}</span>
                          </td>
                          <td className="px-4 py-3 tabular-nums text-foreground">{m.usage_count}</td>
                          <td className="px-4 py-3 tabular-nums text-muted-foreground">
                            {metric(m.completion_rate, "%")}
                          </td>
                          <td className="px-4 py-3 tabular-nums text-muted-foreground">
                            {metric(m.average_learner_score)}
                          </td>
                          <td className="px-4 py-3 tabular-nums text-muted-foreground">
                            {m.confidence_improvement === null ? (
                              "—"
                            ) : (
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1",
                                  m.confidence_improvement < 0 ? "text-danger" : "text-success",
                                )}
                              >
                                {m.confidence_improvement < 0 ? (
                                  <TrendingDown className="h-3 w-3" aria-hidden="true" />
                                ) : (
                                  <Activity className="h-3 w-3" aria-hidden="true" />
                                )}
                                {m.confidence_improvement > 0 ? "+" : ""}
                                {m.confidence_improvement}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 tabular-nums text-muted-foreground">
                            {metric(m.vocabulary_success_rate, "%")}
                          </td>
                          <td className="px-4 py-3 tabular-nums text-muted-foreground">
                            {metric(m.session_abandonment, "%")}
                          </td>
                          <td className="px-4 py-3 tabular-nums text-muted-foreground">
                            {m.learner_satisfaction === null ? "—" : `${m.learner_satisfaction}/5`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <p className="flex items-start gap-2 text-xs text-muted-foreground">
              <BellRing className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              A dash means no data yet, which is not the same as a score of zero. Templates below
              the minimum sample size are marked provisional.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
