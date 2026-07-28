"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Award,
  BookOpen,
  CheckCircle2,
  Clock,
  Flame,
  Loader2,
  Mic,
  RefreshCw,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  getProgressDashboard,
  type ProgressDashboardData,
} from "@/lib/progressDashboard";

export function ProgressDashboardOverview() {
  const [data, setData] = React.useState<ProgressDashboardData | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const loadDashboard = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getProgressDashboard();
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load progress dashboard.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <p className="text-sm text-danger">{error}</p>
        <Button size="sm" variant="outline" className="mt-3" onClick={loadDashboard}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Retry
        </Button>
      </div>
    );
  }

  if (!data) return null;

  const { summary_metrics, primary_metric, trend_lines } = data;

  // PDG-US-10 E-02: Day-1 Empty State View
  if (data.is_empty_state) {
    return (
      <div className="flex flex-col items-center gap-5 rounded-2xl border border-dashed border-border bg-surface-elevated p-8 text-center shadow-sm">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Sparkles className="h-7 w-7" />
        </div>
        <div className="flex flex-col gap-1 max-w-md">
          <h2 className="font-serif text-h2 font-semibold text-foreground">
            Welcome to Your Learning Journey!
          </h2>
          <p className="text-sm text-muted-foreground">
            {data.empty_state_prompt || "Complete your first session to see your progress growth!"}
          </p>
        </div>

        <div className="flex gap-3">
          <Link href="/dashboard/assessment">
            <Button size="sm">Start Baseline Assessment</Button>
          </Link>
          <Link href="/dashboard/explore">
            <Button size="sm" variant="outline">Browse Scenarios</Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* PDG-US-10 E-01: Data Sync Failure Stale Warning Banner */}
      {data.is_stale && (
        <div className="flex items-center gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-xs font-medium text-warning-foreground animate-fade-in">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
          <span>{data.sync_message || "Syncing recent data... Showing last-known-good metrics."}</span>
        </div>
      )}

      {/* Top-Line Primary Metric: Confidence Score (Visually Central & Larger) */}
      <div className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-primary to-primary-hover p-8 text-primary-foreground shadow-md">
        <div className="relative z-10 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-primary-foreground/20 px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider text-white">
                Primary Metric
              </span>
              <span className="text-xs text-primary-foreground/80">Top-Line Confidence</span>
            </div>
            <h2 className="font-serif text-3xl font-bold tracking-tight sm:text-4xl">
              {primary_metric.name}
            </h2>
            <p className="text-xs text-primary-foreground/80 max-w-md">
              {primary_metric.description}
            </p>
          </div>

          <div className="flex flex-col items-start sm:items-end">
            <span className="font-serif text-5xl font-extrabold tracking-tight sm:text-6xl">
              {primary_metric.value}%
            </span>
            <span className="text-xs text-primary-foreground/80">Overall Confidence Score</span>
          </div>
        </div>
      </div>

      {/* 4 Supporting Metrics Grid */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {/* Practice Time */}
        <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
          <div className="flex items-center justify-between text-muted-foreground text-xs font-medium uppercase tracking-wider">
            <span>Practice Time</span>
            <Clock className="h-4 w-4 text-primary" />
          </div>
          <p className="mt-3 font-serif text-2xl font-bold text-foreground">
            {summary_metrics.total_practice_time_minutes} <span className="text-xs font-normal text-muted-foreground">mins</span>
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            ({summary_metrics.total_practice_time_hours} hrs cumulative)
          </p>
        </div>

        {/* Fluency Score */}
        <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
          <div className="flex items-center justify-between text-muted-foreground text-xs font-medium uppercase tracking-wider">
            <span>Fluency Score</span>
            <TrendingUp className="h-4 w-4 text-accent" />
          </div>
          <p className="mt-3 font-serif text-2xl font-bold text-foreground">
            {summary_metrics.fluency_score !== null && summary_metrics.fluency_score !== undefined
              ? `${summary_metrics.fluency_score}%`
              : "N/A"}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">Spoken pace & rhythm</p>
        </div>

        {/* Vocabulary Growth */}
        <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
          <div className="flex items-center justify-between text-muted-foreground text-xs font-medium uppercase tracking-wider">
            <span>Vocab Growth</span>
            <BookOpen className="h-4 w-4 text-success" />
          </div>
          <p className="mt-3 font-serif text-2xl font-bold text-foreground">
            +{summary_metrics.vocabulary_growth_count} <span className="text-xs font-normal text-muted-foreground">words</span>
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">Discovered in scenarios</p>
        </div>

        {/* Completed Sessions & Streak */}
        <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
          <div className="flex items-center justify-between text-muted-foreground text-xs font-medium uppercase tracking-wider">
            <span>Daily Streak</span>
            <Flame className="h-4 w-4 text-warning" />
          </div>
          <p className="mt-3 font-serif text-2xl font-bold text-foreground">
            {summary_metrics.daily_streak_days} <span className="text-xs font-normal text-muted-foreground">days</span>
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {summary_metrics.completed_sessions_count} sessions completed
          </p>
        </div>
      </div>

      {/* Visual Time-Series Trend Line Chart */}
      {trend_lines && trend_lines.length > 0 && (
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="font-serif text-lg font-semibold text-foreground">
              Confidence & Fluency Growth Over Time
            </h3>
            <span className="text-xs text-muted-foreground">
              {trend_lines.length} data points
            </span>
          </div>

          {/* Simple Visual SVG Bar/Line Chart */}
          <div className="mt-6 flex h-44 items-end gap-2 rounded-xl border border-border bg-surface p-4">
            {trend_lines.map((pt, idx) => {
              const confVal = pt.confidence_score ?? 50;
              const heightPct = Math.max(10, Math.min(100, confVal));
              return (
                <div
                  key={idx}
                  className="group relative flex flex-1 flex-col items-center h-full justify-end"
                >
                  {/* Tooltip on hover */}
                  <div className="absolute -top-8 hidden rounded bg-foreground px-2 py-1 text-[10px] text-background group-hover:block z-10 whitespace-nowrap shadow-md">
                    {pt.confidence_score ? `${pt.confidence_score}%` : "N/A"}
                  </div>
                  <div
                    className="w-full rounded-t bg-primary transition-all duration-300 group-hover:bg-primary-hover"
                    style={{ height: `${heightPct}%` }}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
