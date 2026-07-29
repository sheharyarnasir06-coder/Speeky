"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { ShieldAlert, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { LineChart } from "@/components/ui/line-chart";
import { useAuth } from "@/contexts/AuthContext";
import { getSnapshot, type DashboardSnapshot } from "@/lib/adminAnalytics";
import { METRIC_OPTIONS, type MetricKey } from "@/lib/adminAlerts";
import { ApiError } from "@/lib/api";

function isPercentMetric(key: MetricKey): boolean {
  return key === "day1_retention" || key === "day7_retention" || key === "churn_rate";
}

/**
 * The Platform Analytics Dashboard — every anomaly alert deep-links here
 * pre-filtered (?metric=&from=&to=), per GAP-03's acceptance criterion that
 * an alert never opens the generic homepage. Reads from the SAME
 * platform_metrics_service pipeline scheduled reports render from, so the
 * numbers here can never diverge from a report (GAP-04 acceptance criterion).
 */
export default function AdminAnalyticsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const searchParams = useSearchParams();
  const focusedMetric = searchParams.get("metric") as MetricKey | null;
  const dateFrom = searchParams.get("from") ?? undefined;
  const dateTo = searchParams.get("to") ?? undefined;

  const [snapshot, setSnapshot] = React.useState<DashboardSnapshot | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  React.useEffect(() => {
    if (!isAdmin) return;
    getSnapshot(METRIC_OPTIONS.map((m) => m.value), dateFrom, dateTo)
      .then(setSnapshot)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load analytics."));
  }, [isAdmin, dateFrom, dateTo]);

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Admin access required.</p>
      </div>
    );
  }

  // Focused metric (deep-linked from an alert) renders first and full-width,
  // with its anomalous window shaded — the rest follow as small multiples
  // for context. Each metric is its own single-series chart (never a shared
  // axis — the metrics have incompatible scales: counts, percents, currency).
  const orderedMetrics = focusedMetric
    ? [focusedMetric, ...METRIC_OPTIONS.map((m) => m.value).filter((k) => k !== focusedMetric)]
    : METRIC_OPTIONS.map((m) => m.value);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Platform Analytics
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          {focusedMetric
            ? `Filtered to ${METRIC_OPTIONS.find((m) => m.value === focusedMetric)?.label ?? focusedMetric} for the anomalous window.`
            : "Signups, retention, churn, and revenue — the same pipeline scheduled reports and anomaly alerts read from."}
        </p>
        {focusedMetric && dateFrom && dateTo ? (
          <Badge tone="danger" className="mt-3" dot>
            Anomalous window: {dateFrom} to {dateTo}
          </Badge>
        ) : null}
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {!snapshot && !error ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {METRIC_OPTIONS.map((m) => (
            <Skeleton key={m.value} className="h-64 w-full rounded-2xl" />
          ))}
        </div>
      ) : null}

      {snapshot ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {orderedMetrics.map((key) => {
            const series = snapshot.metrics[key];
            const meta = METRIC_OPTIONS.find((m) => m.value === key);
            const isFocused = key === focusedMetric;
            const latest = series?.points.at(-1)?.value;
            return (
              <Card
                key={key}
                elevation="raised"
                className={isFocused ? "border-danger/40 ring-1 ring-danger/20 lg:col-span-2" : undefined}
              >
                <CardHeader className="flex-row items-center justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <TrendingUp className="h-4 w-4 text-primary" aria-hidden="true" />
                      {meta?.label ?? key}
                    </CardTitle>
                    {series && latest !== undefined ? (
                      <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
                        {isPercentMetric(key) ? `${latest}%` : latest.toLocaleString()}
                      </p>
                    ) : null}
                  </div>
                  {series && !series.available ? <Badge tone="neutral">No data source yet</Badge> : null}
                  {isFocused ? <Badge tone="danger">Alert source</Badge> : null}
                </CardHeader>
                <CardContent>
                  {series && !series.available ? (
                    <p className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">
                      No billing/subscription pipeline exists yet — Revenue is wired into
                      thresholds, alerts, and reports, but real figures need that data
                      source connected.
                    </p>
                  ) : (
                    <LineChart
                      points={series?.points ?? []}
                      label={meta?.label ?? key}
                      unit={isPercentMetric(key) ? "%" : undefined}
                      highlightRange={isFocused && dateFrom && dateTo ? { from: dateFrom, to: dateTo } : null}
                    />
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
