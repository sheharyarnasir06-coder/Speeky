"use client";

import * as React from "react";
import {
  Mic,
  Square,
  TrendingUp,
  TrendingDown,
  Info,
  ChevronDown,
  ChevronUp,
  ArrowUpToLine,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { ApiError } from "@/lib/api";
import { useSpeechRecognition } from "@/lib/useSpeechRecognition";
import { useServerPage } from "@/lib/useServerPage";
import {
  startPractice,
  submitBaseline,
  submitAfter,
  getPracticeHistory,
  type AfterResult,
  type ReadMetrics,
  type PaginatedHistory,
} from "@/lib/scriptPractice";
import { cn } from "@/lib/utils";

interface Props {
  script: string;
  context?: string;
}

type Kind = "baseline" | "after";

const HISTORY_PAGE_SIZE = 5;

function MetricChips({ metrics }: { metrics: ReadMetrics }) {
  const items: [string, number | null][] = [
    ["Fluency", metrics.fluency],
    ["Clarity", metrics.pronunciation],
    ["Vocabulary", metrics.vocabulary],
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map(([label, value]) =>
        value === null ? null : (
          <span
            key={label}
            className="rounded-full bg-surface px-2 py-0.5 text-xs text-muted-foreground"
          >
            {label} {Math.round(value)}
          </span>
        ),
      )}
    </div>
  );
}

// US-157: read the script aloud cold (baseline), practice, read again (after).
// Re-record supported: a new baseline resets the final read; each final read is a
// fresh evaluation appended to history.
function ScriptPracticePanelImpl({ script, context }: Props) {
  const { isSupported, isListening, error: micError, start, stop } = useSpeechRecognition();

  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [recording, setRecording] = React.useState<Kind | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [baselineConf, setBaselineConf] = React.useState<number | null>(null);
  const [baselineMetrics, setBaselineMetrics] = React.useState<ReadMetrics | null>(null);
  const [afterResult, setAfterResult] = React.useState<AfterResult | null>(null);

  const startTimeRef = React.useRef<number>(0);

  // Server-paginated history (newest first).
  const historyFetcher = React.useCallback(
    (offset: number, limit: number) => getPracticeHistory(offset, limit),
    [],
  );
  const history = useServerPage<PaginatedHistory>(historyFetcher, HISTORY_PAGE_SIZE);
  const [step, setStep] = React.useState(1);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Script Practice",
  });

  async function handleTranscript(kind: Kind, text: string, durationSeconds: number) {
    setBusy(true);
    setError(null);
    try {
      let id = sessionId;
      if (!id) {
        const s = await startPractice(script, context);
        id = s.session_id;
        setSessionId(id);
      }
      if (kind === "baseline") {
        const b = await submitBaseline(id, text, durationSeconds);
        setBaselineConf(b.baseline_confidence);
        setBaselineMetrics(b.metrics);
        setAfterResult(null); // re-recording the baseline resets the final read
      } else {
        const a = await submitAfter(id, text, durationSeconds);
        setAfterResult(a);
        history.reload(); // new evaluation -> refresh history (jumps to newest)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't score that read. Please try again.");
    } finally {
      setBusy(false);
      setRecording(null);
    }
  }

  function record(kind: Kind) {
    if (!isSupported || isListening || busy) return;
    setError(null);
    startTimeRef.current = Date.now();
    setRecording(kind);
    const ok = start((text) => {
      const durationSeconds = (Date.now() - startTimeRef.current) / 1000;
      if (text.trim()) {
        void handleTranscript(kind, text, durationSeconds);
      } else {
        setRecording(null);
        setError("Didn't catch that — please try reading again.");
      }
    });
    if (!ok) {
      setRecording(null);
      setError("Couldn't start the microphone.");
    }
  }

  if (!isSupported) {
    return (
      <div className="flex items-start gap-2.5 rounded-2xl border border-border bg-surface-elevated px-4 py-3 text-sm text-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        Voice practice needs a browser with speech recognition (Chrome or Edge).
      </div>
    );
  }

  const gain = afterResult?.confidence_gain ?? null;
  const gainPositive = (gain ?? 0) > 0;

  const historyData = history.data;
  const total = historyData?.total ?? 0;
  const entries = historyData?.entries ?? [];
  const lastWindowStart = Math.max(0, total - history.limit);
  const hasMore = history.offset < lastWindowStart;
  const hasPrev = history.offset > 0;

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      {gate}
      <div>
        <h2 className="flex items-center gap-2 font-serif text-lg font-semibold text-foreground">
          <Mic className="h-4 w-4 text-primary" aria-hidden="true" />
          Practice Aloud
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Read the rewrite aloud cold for a baseline, practice it a few times, then read it again to
          see your confidence gain.
        </p>
      </div>

      <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm text-foreground">
        {script}
      </div>

      {error || micError ? (
        <div className="rounded-xl border border-danger/30 bg-danger/5 px-4 py-2.5 text-sm text-foreground">
          {error ?? micError}
        </div>
      ) : null}

      {/* Steps */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* Baseline */}
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">1. Baseline read</span>
            {baselineConf !== null ? (
              <span className="text-lg font-semibold text-foreground">{baselineConf}</span>
            ) : null}
          </div>
          {baselineMetrics ? <MetricChips metrics={baselineMetrics} /> : null}
          <Button
            variant={baselineConf === null ? "primary" : "outline"}
            size="sm"
            onClick={() =>
              isListening && recording === "baseline"
                ? stop()
                : void runWithVoiceReadiness(() => record("baseline"))
            }
            loading={busy && recording === "baseline"}
            disabled={busy && recording !== "baseline"}
          >
            {isListening && recording === "baseline" ? (
              <>
                <Square className="h-4 w-4" aria-hidden="true" />
                Listening… tap to stop
              </>
            ) : (
              <>
                <Mic className="h-4 w-4" aria-hidden="true" />
                {baselineConf === null ? "Record baseline" : "Re-record baseline"}
              </>
            )}
          </Button>
        </div>

        {/* After */}
        <div
          className={cn(
            "flex flex-col gap-3 rounded-xl border border-border bg-surface p-4",
            baselineConf === null && "opacity-60",
          )}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">2. After practice</span>
            {afterResult ? (
              <span className="text-lg font-semibold text-foreground">
                {afterResult.after_confidence}
              </span>
            ) : null}
          </div>
          {afterResult ? <MetricChips metrics={afterResult.after_metrics} /> : null}
          <Button
            variant="primary"
            size="sm"
            onClick={() =>
              isListening && recording === "after"
                ? stop()
                : void runWithVoiceReadiness(() => record("after"))
            }
            loading={busy && recording === "after"}
            disabled={baselineConf === null || (busy && recording !== "after")}
          >
            {isListening && recording === "after" ? (
              <>
                <Square className="h-4 w-4" aria-hidden="true" />
                Listening… tap to stop
              </>
            ) : (
              <>
                <Mic className="h-4 w-4" aria-hidden="true" />
                {afterResult === null ? "Record Final Read" : "Re-record Final Read"}
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Gain + feedback */}
      {afterResult ? (
        <div
          className={cn(
            "flex flex-col gap-1.5 rounded-xl border px-4 py-4 text-center",
            gainPositive
              ? "border-primary/30 bg-primary/5 text-primary"
              : "border-border bg-surface text-muted-foreground",
          )}
        >
          <span className="flex items-center justify-center gap-2 text-lg font-semibold">
            {gainPositive ? (
              <TrendingUp className="h-5 w-5" aria-hidden="true" />
            ) : (
              <TrendingDown className="h-5 w-5" aria-hidden="true" />
            )}
            Confidence {gainPositive ? "+" : ""}
            {gain}
          </span>
          <span className="text-sm text-foreground">{afterResult.feedback}</span>
        </div>
      ) : null}

      {/* History (paginated window of 5) */}
      {total > 0 ? (
        <div className="flex flex-col gap-3 border-t border-border pt-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">Practice history</span>
            {historyData?.average_gain !== null && historyData?.average_gain !== undefined ? (
              <span className="text-xs text-muted-foreground">
                avg gain{" "}
                <span className="font-semibold text-primary">
                  {historyData.average_gain > 0 ? "+" : ""}
                  {historyData.average_gain}
                </span>
              </span>
            ) : null}
          </div>

          <ul
            key={history.offset}
            className={cn(
              "flex flex-col gap-1.5",
              history.direction === "forward" ? "animate-slide-in-right" : "animate-slide-in-left",
            )}
          >
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-3 rounded-lg bg-surface px-3 py-2 text-xs"
              >
                <span className="min-w-0 flex-1 truncate text-muted-foreground" title={entry.script}>
                  {entry.script}
                </span>
                <span className="shrink-0 text-muted-foreground">
                  {entry.baseline_confidence} → {entry.after_confidence}
                </span>
                <span
                  className={cn(
                    "shrink-0 font-semibold",
                    entry.confidence_gain > 0 ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {entry.confidence_gain > 0 ? "+" : ""}
                  {entry.confidence_gain}
                </span>
              </li>
            ))}
          </ul>

          {/* Navigation */}
          {total > history.limit ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">
                Showing {total === 0 ? 0 : history.offset + 1}–
                {Math.min(history.offset + history.limit, total)} of {total}
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">step</span>
                  <input
                    type="number"
                    min={1}
                    value={step}
                    onChange={(e) => setStep(Math.max(1, Number(e.target.value) || 1))}
                    className="h-8 w-14 rounded-lg border border-input bg-surface px-2 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
                    aria-label="Number of entries to advance"
                  />
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasPrev || history.loading}
                  onClick={() => history.goTo(Math.max(0, history.offset - step), "back")}
                >
                  <ChevronUp className="h-4 w-4" aria-hidden="true" />
                  Show Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasMore || history.loading}
                  onClick={() =>
                    history.goTo(Math.min(history.offset + step, lastWindowStart), "forward")
                  }
                >
                  <ChevronDown className="h-4 w-4" aria-hidden="true" />
                  Show More
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!hasPrev || history.loading}
                  onClick={() => history.top()}
                >
                  <ArrowUpToLine className="h-4 w-4" aria-hidden="true" />
                  Back to Top
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export const ScriptPracticePanel = React.memo(ScriptPracticePanelImpl);
