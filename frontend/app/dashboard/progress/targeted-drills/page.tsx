"use client";

import * as React from "react";
import Link from "next/link";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  HelpCircle,
  Loader2,
  Lock,
  Mic,
  SkipForward,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { cn } from "@/lib/utils";
import {
  getTargetedDrills,
  skipTargetedExercises,
  submitTargetedDrill,
  type TargetedDrill,
  type TargetedDrillResult,
} from "@/lib/targetedDrills";

export default function TargetedDrillsPage() {
  const [drills, setDrills] = React.useState<TargetedDrill[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isLocked, setIsLocked] = React.useState(false);
  const [lockedMessage, setLockedMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  // Active drill state
  const [activeDrillIndex, setActiveDrillIndex] = React.useState(0);
  const [isRecording, setIsRecording] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [drillResult, setDrillResult] = React.useState<TargetedDrillResult | null>(null);
  const [skipMessage, setSkipMessage] = React.useState<string | null>(null);

  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const audioChunksRef = React.useRef<Blob[]>([]);
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "targeted drills",
  });

  const loadDrills = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setIsLocked(false);
    setLockedMessage(null);
    setDrillResult(null);
    try {
      const res = await getTargetedDrills();
      setDrills(res.drills || []);
      setActiveDrillIndex(0);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load targeted drills.";
      if (msg.toLowerCase().includes("take your accent assessment") || msg.toLowerCase().includes("unlock")) {
        setIsLocked(true);
        setLockedMessage(msg);
      } else {
        setError(msg);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadDrills();
  }, [loadDrills]);

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
        await handleSubmitDrillAudio(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch (err) {
      setError("Microphone permission denied.");
    }
  };

  const handleStopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleSubmitDrillAudio = async (blob: Blob) => {
    const currentDrill = drills[activeDrillIndex];
    if (!currentDrill) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("target_phoneme", currentDrill.target_phoneme);
      formData.append("prompt_token", currentDrill.prompt_token);
      formData.append("audio", blob, "drill.webm");

      const res = await submitTargetedDrill(currentDrill.drill_id, formData);
      setDrillResult(res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Submission failed.";
      if (msg.toLowerCase().includes("distortion")) {
        setError("Audio distortion detected. Please use a clean recording in a quiet environment.");
      } else {
        setError(msg);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSkipSession = async () => {
    try {
      const res = await skipTargetedExercises();
      setSkipMessage(res.message);
    } catch (err) {
      setSkipMessage("Session skipped. Remember that consistent practice is key!");
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // ACC-US-13 E-01: Locked State if Accent Assessment is incomplete
  if (isLocked) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-5 rounded-2xl border border-border bg-surface-elevated p-8 text-center shadow-sm">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-primary">
          <Lock className="h-6 w-6" />
        </span>
        <h1 className="font-serif text-2xl font-semibold text-foreground">
          Targeted Exercises Locked
        </h1>
        <p className="text-sm text-muted-foreground">
          {lockedMessage || "Take your Accent Assessment first to unlock personalized phoneme drills."}
        </p>
        <Link href="/dashboard/accent-assessment">
          <Button size="sm">Take Accent Assessment First</Button>
        </Link>
      </div>
    );
  }

  const currentDrill = drills[activeDrillIndex];

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      {gate}
      <div className="flex items-center justify-between">
        <Link href="/dashboard/progress">
          <Button variant="ghost" size="sm" className="gap-1.5">
            <ArrowLeft className="h-4 w-4" /> Back to Progress
          </Button>
        </Link>
        <Button variant="outline" size="sm" onClick={handleSkipSession}>
          <SkipForward className="mr-1.5 h-3.5 w-3.5" /> Skip Session
        </Button>
      </div>

      <div className="flex flex-col gap-1">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Targeted Accent Exercises
        </h1>
        <p className="text-sm text-muted-foreground">
          Dynamic drills generated from your identified accent weak points.
        </p>
      </div>

      {skipMessage && (
        <div className="flex items-start gap-2.5 rounded-xl border border-info/30 bg-info/10 px-4 py-3 text-sm text-foreground">
          <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <span>{skipMessage}</span>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <span>{error}</span>
        </div>
      )}

      {currentDrill && (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-8 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary uppercase tracking-wide">
              Target Phoneme: /{currentDrill.target_phoneme}/
            </span>
            <span className="text-xs text-muted-foreground">
              Drill {activeDrillIndex + 1} of {drills.length}
            </span>
          </div>

          <p className="text-xs text-muted-foreground">{currentDrill.issue_description}</p>

          <p className="font-serif text-xl font-medium leading-relaxed text-foreground">
            "{currentDrill.sentence}"
          </p>

          {/* ACC-US-13 E-02: Placement Tip on Repeated Failure Streak (>= 5 Fails) */}
          {(currentDrill.placement_tip || currentDrill.is_paused) && (
            <div className="flex flex-col gap-2 rounded-xl border border-warning/30 bg-warning/10 p-4 text-xs text-foreground">
              <div className="flex items-center gap-2 font-semibold text-warning">
                <AlertTriangle className="h-4 w-4" />
                <span>Tongue & Mouth Placement Tip</span>
              </div>
              <p>{currentDrill.placement_tip || "Focus on tongue placement and blow air gently."}</p>
            </div>
          )}

          {/* Record Button */}
          <div className="mt-4 flex flex-col items-center gap-3">
            <button
              onClick={isRecording ? handleStopRecording : () => void runWithVoiceReadiness(handleStartRecording)}
              disabled={isSubmitting}
              className={cn(
                "flex h-20 w-20 items-center justify-center rounded-full transition-all shadow-md",
                isRecording
                  ? "bg-danger text-white animate-pulse"
                  : "bg-primary text-primary-foreground hover:scale-105"
              )}
            >
              {isSubmitting ? (
                <Loader2 className="h-8 w-8 animate-spin" />
              ) : (
                <Mic className="h-8 w-8" />
              )}
            </button>
            <p className="text-sm text-muted-foreground">
              {isRecording
                ? "Recording... Tap to stop"
                : isSubmitting
                ? "Scoring drill attempt..."
                : "Record your drill attempt"}
            </p>
          </div>
        </div>
      )}

      {/* Drill Scoring Feedback */}
      {drillResult && (
        <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="font-serif text-lg font-semibold text-foreground">Drill Attempt Result</h3>
            <span className="text-2xl font-bold text-primary">{drillResult.overall_score}%</span>
          </div>

          {drillResult.improved_vs_baseline && (
            <div className="flex items-center gap-2 text-xs font-semibold text-success">
              <CheckCircle2 className="h-4 w-4" />
              <span>Measurable improvement vs. baseline assessment!</span>
            </div>
          )}

          {/* ACC-US-11 warning: STT breakdown fallback / model-load / conflict notices */}
          {drillResult.warning && (
            <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs font-medium text-primary">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{drillResult.warning}</span>
            </div>
          )}

          {drillResult.placement_tip && (
            <div className="rounded-xl border border-warning/20 bg-warning/10 p-3 text-xs text-foreground">
              <strong>Placement Tip: </strong>{drillResult.placement_tip}
            </div>
          )}

          {activeDrillIndex < drills.length - 1 && (
            <Button
              className="mt-2 self-end"
              onClick={() => {
                setDrillResult(null);
                setActiveDrillIndex((prev) => prev + 1);
              }}
            >
              Next Drill
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
