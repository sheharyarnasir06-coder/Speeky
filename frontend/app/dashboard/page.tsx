"use client";

import * as React from "react";
import Link from "next/link";
import {
  Briefcase,
  CheckCircle2,
  Coffee,
  MessageCircle,
  Mic,
  Minus,
  Plane,
  Plus,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AccentStalenessBanner } from "@/components/dashboard/AccentStalenessBanner";
import { DailyChallengeCard } from "@/components/dashboard/DailyChallengeCard";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import { MASTERY_METRIC_DEFS } from "@/lib/dashboard-data";
import { getProgressDashboard, type ProgressDashboardData } from "@/lib/progressDashboard";
import { getRecentActivity, type ActivityType, type RecentActivityItem } from "@/lib/recentActivity";
import { GOAL_DASHBOARD_COPY, normalizeGoal } from "@/lib/goals";

interface CategoryStyle {
  icon: typeof Briefcase;
  badge: string;
  gradient: string;
}

const CATEGORY_STYLES: Record<string, CategoryStyle> = {
  Business: {
    icon: Briefcase,
    badge: "bg-primary text-primary-foreground",
    gradient: "bg-gradient-to-br from-primary to-primary-hover",
  },
  Work: {
    icon: Briefcase,
    badge: "bg-primary text-primary-foreground",
    gradient: "bg-gradient-to-br from-primary to-primary-hover",
  },
  Social: {
    icon: Coffee,
    badge: "bg-accent text-accent-foreground",
    gradient: "bg-gradient-to-br from-accent to-accent/70",
  },
  "Daily Life": {
    icon: Users,
    badge: "bg-accent text-accent-foreground",
    gradient: "bg-gradient-to-br from-accent to-accent/70",
  },
  Travel: {
    icon: Plane,
    badge: "bg-foreground text-background",
    gradient: "bg-gradient-to-br from-foreground to-muted-foreground",
  },
};

// Custom (admin-authored) scenarios can carry any category label, so unknown
// ones fall back to a neutral style rather than being dropped.
const DEFAULT_CATEGORY_STYLE: CategoryStyle = {
  icon: Sparkles,
  badge: "bg-secondary text-secondary-foreground",
  gradient: "bg-gradient-to-br from-muted-foreground to-foreground",
};

function getCategoryStyle(category: string): CategoryStyle {
  return CATEGORY_STYLES[category] ?? DEFAULT_CATEGORY_STYLE;
}

// Non-scenario activity types don't carry a scenario category, so they get one
// fixed style per feature instead of going through getCategoryStyle.
const ACTIVITY_TYPE_STYLES: Record<Exclude<ActivityType, "scenario">, CategoryStyle> = {
  conversation: {
    icon: MessageCircle,
    badge: "bg-accent text-accent-foreground",
    gradient: "bg-gradient-to-br from-accent to-accent/70",
  },
  pronunciation: {
    icon: Mic,
    badge: "bg-primary text-primary-foreground",
    gradient: "bg-gradient-to-br from-primary to-primary-hover",
  },
  interview_coach: {
    icon: Briefcase,
    badge: "bg-foreground text-background",
    gradient: "bg-gradient-to-br from-foreground to-muted-foreground",
  },
  accent: {
    icon: Target,
    badge: "bg-secondary text-secondary-foreground",
    gradient: "bg-gradient-to-br from-muted-foreground to-foreground",
  },
};

function getActivityStyle(activity: RecentActivityItem): CategoryStyle {
  return activity.type === "scenario"
    ? getCategoryStyle(activity.subtitle)
    : ACTIVITY_TYPE_STYLES[activity.type];
}

const MASTERY_METRIC_STYLES: Record<
  string,
  { barClassName: string; valueClassName: string }
> = {
  fluency: {
    barClassName: "bg-primary/70 last:bg-primary",
    valueClassName: "text-primary",
  },
  confidence: {
    barClassName: "bg-accent/60 last:bg-accent",
    valueClassName: "text-accent",
  },
  speech: {
    barClassName: "bg-foreground/60 last:bg-foreground",
    valueClassName: "text-foreground",
  },
};

// Which field on the real-time progress payload each mastery card reads —
// "Speech" maps to pronunciation clarity, the closest real signal to what the
// original mock card represented.
const MASTERY_METRIC_SOURCE: Record<string, keyof MetricScores> = {
  fluency: "fluency_score",
  confidence: "confidence_score",
  speech: "pronunciation_score",
};

interface MetricScores {
  confidence_score: number | null;
  fluency_score: number | null;
  vocabulary_score: number | null;
  pronunciation_score: number | null;
}

function activityMetaLabel(activity: RecentActivityItem): {
  label: string;
  icon: "users" | "check";
} {
  const scoreSuffix =
    activity.score != null ? ` · ${Math.round(activity.score)}% ${activity.score_label}` : "";
  if (activity.status === "completed") {
    return { label: `Completed${scoreSuffix}`, icon: "check" };
  }
  if (activity.status === "ended_early") {
    return { label: `Ended Early${scoreSuffix}`, icon: "users" };
  }
  return { label: "In Progress", icon: "users" };
}

// "3h ago" / "Yesterday" / "5d ago" instead of a raw timestamp — scannable at a glance.
function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function DashboardPage() {
  const { user } = useAuth();
  const firstName = user?.name?.trim().split(/\s+/)[0] ?? "there";

  // Goal rides along on the AuthContext user, so a profile-page update (which
  // pushes the refreshed user into that context) reorders this dashboard
  // instantly (US-10 AC) without its own network round trip.
  const goal = normalizeGoal(user?.learningGoal);
  const { subtitle } = GOAL_DASHBOARD_COPY[goal];

  const [dashboard, setDashboard] = React.useState<ProgressDashboardData | null>(null);
  const [dashboardError, setDashboardError] = React.useState<string | null>(null);
  const [activities, setActivities] = React.useState<RecentActivityItem[] | null>(null);
  const [activitiesError, setActivitiesError] = React.useState<string | null>(null);

  React.useEffect(() => {
    getProgressDashboard()
      .then(setDashboard)
      .catch((err) =>
        setDashboardError(err instanceof ApiError ? err.message : "Couldn't load your mastery scores."),
      );

    getRecentActivity()
      .then((data) => setActivities(data.activities))
      .catch((err) =>
        setActivitiesError(err instanceof ApiError ? err.message : "Couldn't load your recent activity."),
      );
  }, []);

  const hasNoSessions = dashboard?.is_empty_state || dashboard?.summary_metrics.completed_sessions_count === 0;

  return (
    <div className="flex flex-col gap-8">
      <AccentStalenessBanner />
      <div className="flex animate-fade-up flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div>
          <h1 className="font-serif text-h1 font-semibold text-foreground">
            Hi, {firstName}!
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <Button type="button" size="md">
          <Plus className="h-4 w-4" aria-hidden="true" />
          Start New Session
        </Button>
      </div>

      <DailyChallengeCard />

      <div className="grid grid-cols-1 gap-6">
        <div
          className="animate-fade-up rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-shadow duration-200 hover:shadow-md"
          style={{ animationDelay: "150ms" }}
        >
          <div className="flex items-center justify-between">
            <h2 className="font-serif text-xl font-semibold text-foreground">
              Learning Mastery
            </h2>
            <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">
              This Week
            </span>
          </div>

          {dashboardError ? (
            <p className="mt-6 text-sm text-danger">{dashboardError}</p>
          ) : !dashboard ? (
            <p className="mt-6 text-sm text-muted-foreground">Loading your mastery scores…</p>
          ) : hasNoSessions ? (
            <div className="mt-6 flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border p-8 text-center">
              <p className="text-sm font-medium text-foreground">
                {dashboard.empty_state_prompt ?? "Complete your first session to see your progress!"}
              </p>
              <p className="max-w-sm text-xs text-muted-foreground">
                Your Fluency, Confidence, and Speech scores will show up here once you finish a
                session.
              </p>
            </div>
          ) : (
            <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-3">
              {MASTERY_METRIC_DEFS.map((metric) => {
                const sourceKey = MASTERY_METRIC_SOURCE[metric.id];
                const value =
                  sourceKey === "confidence_score"
                    ? dashboard.summary_metrics.confidence_score.value
                    : dashboard.summary_metrics[sourceKey];
                const points = dashboard.trend_lines
                  .filter((point) => point[sourceKey] != null)
                  .slice(-5)
                  .map((point) => ({ date: point.date, value: point[sourceKey] as number }));
                // Session-over-session change — the single most motivating number on this
                // card ("+6% since last session" reads as progress; a bare "72%" doesn't.
                const delta =
                  points.length >= 2 ? points[points.length - 1].value - points[points.length - 2].value : null;
                const DeltaIcon = delta == null || Math.abs(delta) < 0.5 ? Minus : delta > 0 ? TrendingUp : TrendingDown;
                const deltaClassName =
                  delta == null || Math.abs(delta) < 0.5
                    ? "text-muted-foreground"
                    : delta > 0
                      ? "text-success"
                      : "text-danger";

                return (
                  <div key={metric.id} className="flex flex-col gap-2">
                    <div className="flex items-center justify-between text-xs font-medium">
                      <span className="tracking-wide text-muted-foreground">{metric.label}</span>
                      <div className="flex items-center gap-2">
                        {delta != null && (
                          <span className={cn("flex items-center gap-0.5", deltaClassName)}>
                            <DeltaIcon className="h-3 w-3" aria-hidden="true" />
                            {Math.abs(delta) < 0.5 ? "±0%" : `${delta > 0 ? "+" : ""}${Math.round(delta)}%`}
                          </span>
                        )}
                        <span
                          className={cn(
                            "font-semibold",
                            MASTERY_METRIC_STYLES[metric.id]?.valueClassName,
                          )}
                        >
                          {value != null ? `${Math.round(value)}%` : "—"}
                        </span>
                      </div>
                    </div>
                    <p className="text-[11px] leading-snug text-muted-foreground">{metric.description}</p>
                    {points.length > 0 ? (
                      <div className="flex h-16 items-end gap-1.5">
                        {points.map((point, i) => (
                          <span
                            key={i}
                            title={`${new Date(point.date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}: ${Math.round(point.value)}%`}
                            className={cn(
                              "flex-1 rounded-sm",
                              MASTERY_METRIC_STYLES[metric.id]?.barClassName,
                            )}
                            style={{ height: `${Math.max(point.value, 4)}%` }}
                          />
                        ))}
                      </div>
                    ) : (
                      <div className="flex h-16 items-center">
                        <p className="text-xs text-muted-foreground">Not enough data yet</p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-xl font-semibold text-foreground">
            Recent Activity
          </h2>
        </div>

        {activitiesError ? (
          <p className="mt-4 text-sm text-danger">{activitiesError}</p>
        ) : !activities ? (
          <p className="mt-4 text-sm text-muted-foreground">Loading your recent activity…</p>
        ) : activities.length === 0 ? (
          <div className="mt-4 flex min-h-[25vh] flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-border p-8 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-primary">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="flex flex-col gap-1">
              <h3 className="font-serif text-lg font-semibold text-foreground">
                No activity yet
              </h3>
              <p className="max-w-sm text-xs text-muted-foreground">
                Start a scenario, conversation, or any practice session — it'll show up here once
                you begin.
              </p>
            </div>
            <Button href="/dashboard/explore" size="sm">
              Explore Practice Modes
            </Button>
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
            {activities.map((activity, index) => {
              const style = getActivityStyle(activity);
              const TypeIcon = style.icon;
              const meta = activityMetaLabel(activity);
              return (
                <Link
                  key={`${activity.type}-${activity.activity_id}`}
                  href={activity.href}
                  className="group animate-fade-up overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-sm transition-all duration-200 hover:-translate-y-1 hover:shadow-md"
                  style={{ animationDelay: `${200 + index * 80}ms` }}
                >
                  <div
                    className={cn(
                      "relative flex h-36 items-center justify-center",
                      style.gradient,
                    )}
                  >
                    <TypeIcon
                      className="h-10 w-10 text-primary-foreground/90 transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6"
                      aria-hidden="true"
                    />
                    <span
                      className={cn(
                        "absolute left-3 top-3 rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-wide",
                        style.badge,
                      )}
                    >
                      {activity.subtitle}
                    </span>
                    <span className="absolute right-3 top-3 rounded-md bg-background/80 px-2 py-1 text-[10px] font-medium text-foreground">
                      {timeAgo(activity.occurred_at)}
                    </span>
                  </div>
                  <div className="flex flex-col gap-2 p-5">
                    <h3 className="font-serif text-lg font-semibold text-foreground">
                      {activity.title}
                    </h3>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      {meta.icon === "check" ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                      ) : (
                        <Users className="h-3.5 w-3.5" aria-hidden="true" />
                      )}
                      {meta.label}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      <button
        type="button"
        aria-label="Start voice session"
        className="fixed bottom-8 right-8 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md transition-all duration-200 hover:scale-110 hover:bg-primary-hover hover:shadow-lg active:scale-95"
      >
        <Mic className="h-5 w-5" aria-hidden="true" />
      </button>
    </div>
  );
}
