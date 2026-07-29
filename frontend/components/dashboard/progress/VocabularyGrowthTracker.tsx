"use client";

import * as React from "react";
import { BookOpen, ChevronRight, Clock, Gauge, Sparkles, TrendingUp } from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  getProgressDashboardOverview,
  type ProgressDashboardOverview,
} from "@/lib/progressDashboard";
import { cn } from "@/lib/utils";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SkeletonCard } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { VocabularyDrillDownModal } from "./VocabularyDrillDownModal";

function formatPracticeTime(minutes: number): string {
  if (minutes < 1) return "< 1 min";
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  if (hours === 0) return `${mins} min`;
  return `${hours}h ${mins}m`;
}

function formatScore(score: number | null): string {
  return score === null ? "—" : `${Math.round(score)}/100`;
}

interface MetricTile {
  id: string;
  label: string;
  value: string;
  icon: typeof Clock;
  /** 0-100 for the inline meter; null for non-scored metrics like time. */
  meter: number | null;
}

/** PDG-US-14: Progress Dashboard - Vocabulary Growth Tracker. */
export function VocabularyGrowthTracker() {
  const [overview, setOverview] = React.useState<ProgressDashboardOverview | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isDrillDownOpen, setIsDrillDownOpen] = React.useState(false);

  React.useEffect(() => {
    getProgressDashboardOverview()
      .then(setOverview)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Something went wrong."))
      .finally(() => setIsLoading(false));
  }, []);

  if (isLoading) return <SkeletonCard />;

  if (error) {
    return (
      <Card className="p-6">
        <Alert tone="danger" title="Couldn't load your progress">
          {error}
        </Alert>
      </Card>
    );
  }

  if (!overview) return null;

  const { metrics, vocabulary_growth: growth, vocabulary_history: history } = overview;

  const tiles: MetricTile[] = [
    { id: "time", label: "Practice Time", value: formatPracticeTime(metrics.practice_time_minutes), icon: Clock, meter: null },
    { id: "confidence", label: "Confidence", value: formatScore(metrics.confidence_score), icon: Gauge, meter: metrics.confidence_score },
    { id: "fluency", label: "Fluency", value: formatScore(metrics.fluency_score), icon: TrendingUp, meter: metrics.fluency_score },
    { id: "vocabulary", label: "Vocabulary", value: formatScore(metrics.vocabulary_score), icon: BookOpen, meter: metrics.vocabulary_score },
  ];

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-h2 text-foreground">Vocabulary Growth</h2>
        <Badge tone="brand" size="md">All Time</Badge>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {tiles.map((tile) => {
          const isVocabularyTile = tile.id === "vocabulary";
          return (
            <StatTile
              key={tile.id}
              label={tile.label}
              value={tile.value}
              icon={tile.icon}
              meter={tile.meter}
              hint={isVocabularyTile ? "See every word you've collected" : undefined}
              onClick={isVocabularyTile ? () => setIsDrillDownOpen(true) : undefined}
            />
          );
        })}
      </div>

      {!overview.has_data ? (
        <div className="mt-6 flex flex-col items-center gap-2 rounded-xl border border-dashed border-border p-8 text-center">
          <Sparkles className="h-6 w-6 text-primary" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">
            Your vocabulary journey starts here. {growth.message}
          </p>
          <a
            href="/dashboard/explore"
            className="mt-2 text-sm font-medium text-primary hover:underline"
          >
            Start a Scenario
          </a>
        </div>
      ) : (
        <div className="mt-6 flex flex-col gap-4">
          <div
            className={cn(
              "flex flex-col gap-2 rounded-xl px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between",
              growth.is_zero_growth ? "bg-secondary text-secondary-foreground" : "bg-success/10 text-foreground",
            )}
          >
            <span className="font-medium">
              {growth.is_zero_growth
                ? growth.message
                : `+${growth.new_words_count} new ${growth.new_words_count === 1 ? "word" : "words"} last session`}
            </span>
            {!growth.is_zero_growth && growth.new_words && growth.new_words.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {growth.new_words.map((word) => (
                  <span
                    key={word}
                    className="rounded-full bg-success/15 px-2.5 py-0.5 text-xs font-medium text-success"
                  >
                    {word}
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          {history.length > 1 ? (
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Vocabulary Score Trend
              </p>
              <div className="flex h-20 items-end gap-1.5">
                {history.map((point) => (
                  <span
                    key={point.date}
                    title={`${new Date(point.date).toLocaleDateString()}: ${point.vocabulary_score}`}
                    className="flex-1 rounded-sm bg-primary/70 last:bg-primary"
                    style={{ height: `${Math.max(4, point.vocabulary_score)}%` }}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}

      <VocabularyDrillDownModal open={isDrillDownOpen} onClose={() => setIsDrillDownOpen(false)} />
    </Card>
  );
}