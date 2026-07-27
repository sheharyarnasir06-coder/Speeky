"use client";

import * as React from "react";
import { AlertCircle, Award, Lightbulb, Loader2, Sparkles, Volume2 } from "lucide-react";
import {
  getPublicSpeakingFillerWords,
  type FillerWordAnalysisResponse,
} from "@/lib/fillerWords";

interface Props {
  sessionId: string;
  // Defaults to the Public Speaking endpoint; Mock Interview passes
  // getInterviewCoachFillerWords to reuse this same scorecard UI (US-102).
  fetchFn?: (sessionId: string) => Promise<FillerWordAnalysisResponse>;
}

export function FillerWordsScorecardSection({ sessionId, fetchFn = getPublicSpeakingFillerWords }: Props) {
  const [data, setData] = React.useState<FillerWordAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    fetchFn(sessionId)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load filler words."))
      .finally(() => setIsLoading(false));
  }, [sessionId, fetchFn]);

  if (isLoading) {
    return (
      <div className="rounded-xl border border-border bg-surface p-4 text-center text-xs text-muted-foreground">
        <Loader2 className="mx-auto h-4 w-4 animate-spin text-primary" />
        <span className="mt-1 block">Analyzing filler words timeline...</span>
      </div>
    );
  }

  if (error || !data) {
    return null; // Gracefully omit if no filler data available
  }

  // PSC-US-08 E-03: Zero Filler Words — Flawless Delivery Badge
  if (data.flawless_delivery || data.total_filler_count === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl border border-success/30 bg-gradient-to-br from-success/10 to-success/5 p-6 text-center shadow-sm">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success text-white shadow-md">
          <Award className="h-6 w-6" />
        </div>
        <span className="rounded-full bg-success/20 px-3 py-1 text-xs font-bold uppercase tracking-wider text-success">
          {data.badge || "Flawless Delivery"}
        </span>
        <h3 className="font-serif text-lg font-semibold text-foreground">
          Zero Filler Words Detected!
        </h3>
        <p className="max-w-md text-xs text-muted-foreground">
          {data.analysis_summary || "Outstanding! You maintained clear, uninterrupted speech without nervous verbal tics."}
        </p>

        {/* Actionable tip for maintaining pause discipline */}
        <div className="mt-2 flex items-center gap-2 rounded-xl bg-surface px-4 py-2.5 text-xs text-muted-foreground border border-border">
          <Lightbulb className="h-4 w-4 text-primary shrink-0" />
          <span>{data.actionable_tip}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-serif text-lg font-semibold text-foreground">
            Filler Word Breakdown & Timeline
          </h3>
          <p className="text-xs text-muted-foreground">
            Precise timeline markers for nervous verbal tics.
          </p>
        </div>
        <span className="rounded-full bg-warning/10 px-3 py-1 text-xs font-semibold text-warning border border-warning/20">
          {data.total_filler_count} Total Fillers
        </span>
      </div>

      {/* Waveform / Timeline Visual Marker Track */}
      <div>
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Speech Timeline Markers
        </span>
        <div className="mt-3 relative flex h-16 w-full items-center rounded-xl border border-border bg-surface px-4">
          {/* Background waveform mock bars */}
          <div className="absolute inset-x-4 flex h-8 items-center gap-1 opacity-20">
            {Array.from({ length: 40 }).map((_, i) => (
              <span
                key={i}
                className="flex-1 rounded-full bg-foreground"
                style={{ height: `${(i % 5 + 2) * 15}%` }}
              />
            ))}
          </div>

          {/* Timeline Filler Markers */}
          <div className="relative z-10 flex w-full items-center justify-start gap-3 overflow-x-auto py-2">
            {data.timeline_markers.map((m, idx) => (
              <div
                key={idx}
                className="flex shrink-0 items-center gap-1 rounded-md border border-warning/40 bg-warning/20 px-2 py-1 text-xs font-medium text-warning-foreground shadow-sm"
              >
                <span>"{m.word}"</span>
                {m.start_time !== undefined && m.start_time !== null && (
                  <span className="text-[10px] text-muted-foreground">({m.start_time}s)</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Frequency List */}
      <div>
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Frequency Breakdown
        </span>
        <div className="mt-2 flex flex-wrap gap-2">
          {data.filler_counts.map((fc, idx) => (
            <div
              key={idx}
              className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium"
            >
              <span className="font-semibold text-foreground capitalize">{fc.word}:</span>
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary font-bold">
                {fc.count} times
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Actionable Tip */}
      <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-primary/5 p-4 text-xs text-foreground">
        <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div>
          <strong className="text-primary font-semibold">Actionable Tip: </strong>
          <span>{data.actionable_tip}</span>
        </div>
      </div>
    </div>
  );
}
