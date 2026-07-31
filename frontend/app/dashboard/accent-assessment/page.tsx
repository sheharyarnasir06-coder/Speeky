"use client";

import * as React from "react";
import {
  AlertCircle,
  Info,
  Loader2,
  Mic,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { WordByWordDisplay } from "@/components/dashboard/WordByWordDisplay";
import { cn } from "@/lib/utils";
import {
  getTargetPassage,
  rejectionFromError,
  submitPassageAssessment,
  type AccentAssessmentResult,
  type TargetPassageResponse,
} from "@/lib/accentAssessment";

function wordCount(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

export default function AccentAssessmentPage() {
  const [passageData, setPassageData] = React.useState<TargetPassageResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isRecording, setIsRecording] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [staleToken, setStaleToken] = React.useState(false);
  const [result, setResult] = React.useState<AccentAssessmentResult | null>(null);

  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const audioChunksRef = React.useRef<Blob[]>([]);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Accent Assessment",
  });

  const loadPassage = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setStaleToken(false);
    setResult(null);
    try {
      const data = await getTargetPassage();
      setPassageData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load passage.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadPassage();
  }, [loadPassage]);

  const handleStartRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        await handleAssessPassageAudio(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setError("Microphone permission denied or unsupported.");
    }
  };

  const handleStopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleAssessPassageAudio = async (blob: Blob) => {
    if (!passageData) return;
    setIsSubmitting(true);
    setError(null);
    setStaleToken(false);
    try {
      const formData = new FormData();
      formData.append("prompt_token", passageData.prompt_token);
      formData.append("audio", blob, "accent_passage.webm");

      const res = await submitPassageAssessment(passageData.passage_id, formData);
      setResult(res);
    } catch (err) {
      // Structured rejection (playback detected, incomplete reading, quality
      // issue, stale token, ...) — carries the real message; each rejection is
      // judged independently, so the user can just try again.
      const rejection = rejectionFromError(err);
      if (rejection) {
        setError(rejection.message);
        // ACC-US-01 E-04: this passage's prompt token is dead (stale/reused) — the mic
        // button would just fail again with the same token, so surface a direct
        // "fetch new passage" recovery right here instead of only in the results view.
        if (rejection.reason === "stale_prompt_token") {
          setStaleToken(true);
        }
        return;
      }

      setError(err instanceof Error ? err.message : "Assessment failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const overallScore = result
    ? Math.round(
        (result.pronunciation_score +
          result.stress_score +
          result.rhythm_score +
          result.intonation_score +
          result.clarity_score) /
          5
      )
    : null;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      {gate}
      <div className="flex flex-col gap-1">
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Accent Assessment
        </h1>
        <p className="text-sm text-muted-foreground">
          Read the passage aloud to measure rhythm, stress, intonation, and clarity.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div className="flex flex-1 flex-wrap items-center justify-between gap-2">
            <span>{error}</span>
            {staleToken && (
              <Button size="sm" variant="outline" onClick={loadPassage}>
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Fetch New Passage
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Randomized Live Passage */}
      {passageData && !result && (
        <div className="rounded-2xl border border-border bg-surface-elevated p-8 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Passage ({wordCount(passageData.text)} words)
            </span>
            <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
              Live Token Active
            </span>
          </div>

          <p className="mt-4 font-serif text-lg leading-relaxed text-foreground">
            "{passageData.text}"
          </p>

          <div className="mt-8 flex flex-col items-center gap-4">
            <button
              onClick={isRecording ? handleStopRecording : () => void runWithVoiceReadiness(handleStartRecording)}
              disabled={isSubmitting}
              // Icon-only control: without an explicit name a screen reader announces
              // only "button". aria-pressed exposes the record/stop state too, so the
              // control is usable without seeing the colour change.
              aria-label={
                isSubmitting
                  ? "Analysing your recording"
                  : isRecording
                    ? "Stop recording"
                    : "Start recording the passage"
              }
              aria-pressed={isRecording}
              className={cn(
                "flex h-20 w-20 items-center justify-center rounded-full shadow-md",
                "transition-transform duration-fast ease-spring motion-reduce:transition-none",
                isRecording
                  ? "bg-danger text-white animate-pulse motion-reduce:animate-none"
                  : "bg-primary text-primary-foreground hover:scale-105 motion-reduce:hover:scale-100"
              )}
            >
              {isSubmitting ? (
                <Loader2 className="h-8 w-8 animate-spin" aria-hidden="true" />
              ) : (
                <Mic className="h-8 w-8" aria-hidden="true" />
              )}
            </button>
            <p className="text-sm text-muted-foreground">
              {isRecording
                ? "Recording passage... Tap when finished"
                : isSubmitting
                ? "Analyzing rhythm & stress patterns..."
                : "Read the full passage into your microphone"}
            </p>
          </div>
        </div>
      )}

      {/* Assessment Results View */}
      {result && (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-serif text-xl font-semibold text-foreground">
                Accent Profile Results
              </h2>
              <p className="text-xs text-muted-foreground">
                Model: {result.model_used || "Standard Phonetic Model"}
              </p>
            </div>
            <span className="text-3xl font-bold text-primary">
              {overallScore}%
            </span>
          </div>

          {/* 5 Sub-Metric Score Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.pronunciation_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Pronunciation</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.stress_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Word Stress</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.rhythm_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Rhythm</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.intonation_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Intonation</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.clarity_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Clarity</div>
            </div>
          </div>

          {/* ACC-US-14 / ACC-US-11: distortion fallback, unmapped-accent, or model-load warnings */}
          {result.warning && (
            <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-xs font-medium text-primary">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{result.warning}</span>
            </div>
          )}

          {/* Word by word breakdown */}
          {result.words && result.words.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-foreground">Word by word</h3>
              <WordByWordDisplay className="mt-3" words={result.words.map((w) => ({ word: w.word, status: w.status }))} />
            </div>
          )}

          {/* Detected Weak Points */}
          {result.weak_points && result.weak_points.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-foreground">Identified Target Areas</h3>
              <div className="mt-3 grid gap-2">
                {result.weak_points.map((wp, idx) => (
                  <div key={idx} className="rounded-xl border border-border bg-surface p-3 text-xs">
                    <strong className="text-primary uppercase tracking-wide">{wp.issue}: </strong>
                    <span className="text-muted-foreground">{wp.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" onClick={loadPassage}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Try Another Passage
            </Button>
            <Button href="/dashboard/progress/targeted-drills">
              Practice Targeted Exercises
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
