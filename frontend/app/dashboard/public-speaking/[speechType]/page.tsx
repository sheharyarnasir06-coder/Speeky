"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle,
  Clock,
  Lightbulb,
  Mic,
  Send,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceReadinessGate } from "@/components/common/VoiceReadinessGate";
import { MilestoneCelebrationModal } from "@/components/dashboard/MilestoneCelebrationModal";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { FillerWordsScorecardSection } from "@/components/dashboard/public-speaking/FillerWordsScorecardSection";
import { ApiError } from "@/lib/api";
import {
  startPublicSpeakingSession,
  submitPublicSpeakingTurn,
  submitPublicSpeakingQa,
  type SpeechType,
} from "@/lib/publicSpeaking";
import { buildVoiceWsUrl, useVoiceSocket, type VoiceFeatures } from "@/lib/useVoiceSocket";
import { usePracticeTimePing } from "@/lib/usePracticeTimePing";

const SPEECH_TYPE_CONFIG: Record<string, { label: string; description: string; ideal_wpm: string }> = {
  business_pitch: {
    label: "Business Pitch",
    description: "Structure: Hook → Problem → Solution → Ask",
    ideal_wpm: "130-160 WPM",
  },
  casual_event: {
    label: "Casual Event Speech",
    description: "Focus on warmth, storytelling, and emotional connection",
    ideal_wpm: "120-150 WPM",
  },
  motivational: {
    label: "Motivational Speech",
    description: "Prioritize energy, tone variation, and strategic pausing",
    ideal_wpm: "130-160 WPM",
  },
  classroom: {
    label: "Classroom Presentation",
    description: "Include clear transitions and minimize filler words",
    ideal_wpm: "130-150 WPM",
  },
  ted_talk: {
    label: "TED-Style Talk",
    description: "Craft a narrative arc with personal stories",
    ideal_wpm: "130-150 WPM",
  },
};

export default function PublicSpeakingSessionPage() {
  const params = useParams();
  const router = useRouter();
  const speechType = params.speechType as string;
  const config = SPEECH_TYPE_CONFIG[speechType] || SPEECH_TYPE_CONFIG.business_pitch;

  const [inputMode, setInputMode] = React.useState<"audio" | "text">("audio");
  const [textContent, setTextContent] = React.useState("");
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [scorecard, setScorecard] = React.useState<any>(null);
  const [qaQuestion, setQaQuestion] = React.useState<string | null>(null);
  const [qaResponse, setQaResponse] = React.useState("");
  const [qaScore, setQaScore] = React.useState<any>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showQa, setShowQa] = React.useState(false);

  const sessionIdRef = React.useRef<string | null>(null);
  sessionIdRef.current = sessionId;
  const voiceStartedAt = React.useRef<number | null>(null);
  const voiceDurationRef = React.useRef<number>(0);
  const featuresRef = React.useRef({
    has: false,
    word_timings: [] as { word: string; start: number; end: number }[],
    duration_seconds: 0,
    avg_db: undefined as number | undefined,
    pitch_range_semitones: 0,
  });
  const getWsUrl = React.useCallback(() => {
    const id = sessionIdRef.current;
    if (!id) return null;
    return buildVoiceWsUrl(`/public-speaking/${id}/voice-ws`);
  }, []);

  // Live text is spliced directly into the (editable) textarea instead of a separate
  // preview line — but the textarea is editable at any time, so a naive splice risks
  // clobbering an in-progress edit. committedTextRef is the "locked" baseline (real,
  // finalized transcript text, or whatever the user typed); splicedPartialRef is the
  // live guess currently appended after it, or null when no live guess is showing.
  // Each update only touches the textarea if its current value still exactly matches
  // what we last spliced — the moment the user types anything, both callbacks back off
  // and leave their edit alone until the next utterance starts.
  const committedTextRef = React.useRef("");
  const splicedPartialRef = React.useRef<string | null>(null);

  const onPartial = React.useCallback((text: string) => {
    if (!text) return;
    setTextContent((current) => {
      const base = committedTextRef.current;
      const expected =
        splicedPartialRef.current === null ? base : `${base}${base ? " " : ""}${splicedPartialRef.current}`;
      if (current !== expected) return current; // user has edited — leave it alone
      if (splicedPartialRef.current === null) committedTextRef.current = current; // snapshot baseline
      splicedPartialRef.current = text;
      return `${committedTextRef.current}${committedTextRef.current ? " " : ""}${text}`;
    });
  }, []);

  const {
    isVoiceActive,
    isConnectingVoice,
    isStoppingVoice,
    voiceStatus,
    error: voiceError,
    startVoice,
    stopVoice,
  } = useVoiceSocket(
    getWsUrl,
    (text, features?: VoiceFeatures) => {
      setTextContent((prev) => {
        const base = committedTextRef.current;
        const expected =
          splicedPartialRef.current === null ? null : `${base}${base ? " " : ""}${splicedPartialRef.current}`;
        // Still showing our own live guess untouched? Replace it with the real text
        // instead of appending on top of the guess. Otherwise (no live guess, or the
        // user edited) fall back to the original append-to-whatever's-there behavior.
        const from = expected !== null && prev === expected ? base : prev;
        const next = from.trim() ? `${from.trim()} ${text}` : text;
        committedTextRef.current = next; // locked
        splicedPartialRef.current = null; // ready for the next utterance
        return next;
      });
      if (features) {
        const acc = featuresRef.current;
        if (features.word_timings) acc.word_timings.push(...features.word_timings);
        if (typeof features.duration_seconds === "number") acc.duration_seconds += features.duration_seconds;
        if (typeof features.avg_db === "number") acc.avg_db = features.avg_db;
        if (typeof features.pitch_range_semitones === "number")
          acc.pitch_range_semitones = Math.max(acc.pitch_range_semitones, features.pitch_range_semitones);
        acc.has = true;
      }
    },
    onPartial,
  );
  const { gate, runWithVoiceReadiness } = useVoiceReadinessGate({
    featureName: "Public Speaking Practice",
  });

  // PDG-US-15: heartbeat pings while this speech is the active practice
  // session, crediting lifetime practice time and surfacing any milestone
  // that unlocks mid-session. "Active" until scored, and — if a follow-up
  // Q&A got triggered — until that's answered too.
  const isSessionDone = scorecard !== null && (qaQuestion === null || qaScore !== null);
  const { newlyUnlocked, dismissMilestone } = usePracticeTimePing(
    "public_speaking",
    sessionId,
    sessionId !== null && !isSessionDone,
  );

  const handleStartVoice = async () => {
    if (isVoiceActive) return;
    voiceStartedAt.current = performance.now();
    committedTextRef.current = textContent;
    splicedPartialRef.current = null;
    await startVoice();
  };

  const handleStopVoice = async () => {
    await stopVoice();
    if (voiceStartedAt.current != null) {
      voiceDurationRef.current += (performance.now() - voiceStartedAt.current) / 1000;
      voiceStartedAt.current = null;
    }
  };

  const handleStartSession = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      const data = await startPublicSpeakingSession({
        speech_type: speechType as SpeechType,
        input_mode: inputMode,
      });
      setSessionId(data.session_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start session");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitSpeech = async () => {
    if (!sessionId) return;
    if (isVoiceActive) await handleStopVoice();
    const content = textContent.trim();
    if (!content) {
      setError(
        inputMode === "audio"
          ? "Record your speech before submitting."
          : "Enter your speech before submitting.",
      );
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const f = featuresRef.current;
      const data = await submitPublicSpeakingTurn(sessionId, {
        text_content: content,
        duration_seconds:
          inputMode === "audio"
            ? Math.max(1, f.duration_seconds || voiceDurationRef.current)
            : null,
        audio_features: f.has
          ? {
              word_timings: f.word_timings,
              avg_db: f.avg_db,
              pitch_range_semitones: f.pitch_range_semitones,
              duration_seconds: f.duration_seconds,
            }
          : undefined,
        is_final: true,
      });
      setScorecard(data.scorecard);
      if (data.qa_triggered) {
        setQaQuestion(data.ai_question ?? null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit speech");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitQaResponse = async () => {
    if (!sessionId) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const data = await submitPublicSpeakingQa(sessionId, {
        audio_data: null,
        text_content: qaResponse,
      });
      setQaScore(data.qa_score);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit Q&A response");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {gate}
      <MilestoneCelebrationModal
        milestone={newlyUnlocked[0] ?? null}
        onClose={() => newlyUnlocked[0] && dismissMilestone(newlyUnlocked[0].hours)}
      />
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.back()}
          className="!w-9 shrink-0 !px-0"
        >
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div>
          <h1 className="font-serif text-h2 font-semibold text-foreground">
            {config.label}
          </h1>
          <p className="text-sm text-muted-foreground">{config.description}</p>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
          {error}
        </div>
      )}

      {!sessionId ? (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div>
            <h2 className="font-semibold text-foreground">Session Setup</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose your input mode and start your practice session.
            </p>
          </div>

          <div className="flex gap-4">
            <button
              onClick={() => setInputMode("audio")}
              className={cn(
                "flex flex-1 flex-col items-center gap-3 rounded-xl border-2 p-4 transition-all",
                inputMode === "audio"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50"
              )}
            >
              <Mic className="h-8 w-8 text-primary" />
              <div className="text-center">
                <div className="font-medium text-foreground">Voice</div>
                <div className="text-xs text-muted-foreground">Speak naturally</div>
              </div>
            </button>

            <button
              onClick={() => setInputMode("text")}
              className={cn(
                "flex flex-1 flex-col items-center gap-3 rounded-xl border-2 p-4 transition-all",
                inputMode === "text"
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50"
              )}
            >
              <Send className="h-8 w-8 text-primary" />
              <div className="text-center">
                <div className="font-medium text-foreground">Text</div>
                <div className="text-xs text-muted-foreground">Type your speech</div>
              </div>
            </button>
          </div>

          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-foreground">Target Pace: {config.ideal_wpm}</span>
            </div>
          </div>

          <Button
          onClick={
            inputMode === "audio"
              ? () => void runWithVoiceReadiness(handleStartSession)
              : handleStartSession
          }
            disabled={isSubmitting}
            className="w-full"
          >
            {isSubmitting ? "Starting..." : "Start Session"}
          </Button>
        </div>
      ) : !scorecard ? (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div>
            <h2 className="font-semibold text-foreground">Deliver Your Speech</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {inputMode === "audio"
                ? "Record your speech when ready. Speak clearly and at a natural pace."
                : "Type your speech below. Focus on structure and clarity."}
            </p>
          </div>

          {inputMode === "audio" ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-border p-6">
                <button
                  onClick={isVoiceActive ? handleStopVoice : () => void runWithVoiceReadiness(handleStartVoice)}
                  disabled={isConnectingVoice || isStoppingVoice}
                  className={cn(
                    "flex h-20 w-20 items-center justify-center rounded-full transition-all disabled:opacity-60",
                    isVoiceActive
                      ? "bg-danger text-white animate-pulse"
                      : "bg-primary text-white hover:scale-110",
                  )}
                >
                  <Mic className="h-10 w-10" />
                </button>
                <div className="text-center">
                  <div className="font-medium text-foreground">
                    {isConnectingVoice
                      ? "Connecting..."
                      : isVoiceActive
                        ? "Recording — tap to stop"
                        : "Tap to Record"}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {voiceStatus || "We transcribe as you speak — review below before submitting."}
                  </div>
                </div>
              </div>
              <Textarea
                label="Transcript (editable)"
                value={textContent}
                onChange={(e) => setTextContent(e.target.value)}
                placeholder="Your spoken words appear here..."
                rows={6}
              />
              {voiceError ? (
                <p className="text-sm text-danger">{voiceError}</p>
              ) : null}
            </div>
          ) : (
            <Textarea
              label="Your speech"
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              placeholder="Type your speech here..."
              rows={8}
            />
          )}

          <Button
            onClick={handleSubmitSpeech}
            disabled={isSubmitting || isVoiceActive || !textContent.trim()}
            className="w-full"
          >
            {isSubmitting ? "Analyzing..." : "Submit for Analysis"}
          </Button>
        </div>
      ) : qaQuestion && showQa ? (
        !qaScore ? (
          <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
            <div>
              <h2 className="font-semibold text-foreground">Audience Q&A</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                An audience member has a follow-up question. Respond impromptu.
              </p>
            </div>

            <div className="rounded-lg bg-secondary/20 p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-white shrink-0">
                  ?
                </div>
                <div>
                  <div className="font-medium text-foreground">Question</div>
                  <p className="mt-1 text-sm text-foreground">{qaQuestion}</p>
                </div>
              </div>
            </div>

            <Textarea
              label="Your response"
              value={qaResponse}
              onChange={(e) => setQaResponse(e.target.value)}
              placeholder="Type your response..."
              rows={5}
            />

            <Button
              onClick={handleSubmitQaResponse}
              disabled={isSubmitting || !qaResponse.trim()}
              className="w-full"
            >
              {isSubmitting ? "Evaluating..." : "Submit Response"}
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
            <div className="flex items-center gap-3">
              <CheckCircle className="h-8 w-8 text-success" />
              <div>
                <h2 className="font-semibold text-foreground">Q&A Evaluation</h2>
                <p className="text-sm text-muted-foreground">
                  Here's how you handled the audience question.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <ScoreCard label="Composure" score={qaScore.composure} />
              <ScoreCard label="Relevance" score={qaScore.relevance} />
            </div>

            <div className="rounded-lg bg-secondary/20 p-4">
              <div className="flex items-start gap-3">
                <Lightbulb className="mt-0.5 h-5 w-5 text-primary shrink-0" />
                <div>
                  <div className="font-medium text-foreground">Feedback</div>
                  <p className="mt-1 text-sm text-muted-foreground">{qaScore.feedback}</p>
                </div>
              </div>
            </div>

            <Button onClick={() => router.push("/dashboard/public-speaking")} className="w-full">
              Back to Public Speaking Coach
            </Button>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6">
          <div className="flex items-center gap-3">
            <CheckCircle className="h-8 w-8 text-success" />
            <div>
              <h2 className="font-semibold text-foreground">Analysis Complete</h2>
              <p className="text-sm text-muted-foreground">
                Great job! Here's your performance breakdown.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <ScoreCard label="Overall" score={scorecard.overall_score} />
            <ScoreCard label="Pacing" score={scorecard.pacing} />
            <ScoreCard label="Tone" score={scorecard.tone_variation} />
            <ScoreCard label="Clarity" score={scorecard.voice_clarity} />
          </div>

          <div className="rounded-lg bg-muted/50 p-4">
            <div className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-foreground">
                Speaking Pace: {scorecard.words_per_minute?.toFixed(1)} WPM
              </span>
            </div>
          </div>

          {sessionId && <FillerWordsScorecardSection sessionId={sessionId} />}


          <div className="rounded-lg bg-secondary/20 p-4">
            <div className="flex items-start gap-3">
              <Lightbulb className="mt-0.5 h-5 w-5 text-primary shrink-0" />
              <div>
                <div className="font-medium text-foreground">Key Feedback</div>
                <p className="mt-1 text-sm text-muted-foreground">{scorecard.summary}</p>
              </div>
            </div>
          </div>

          {scorecard.actionable_tips && scorecard.actionable_tips.length > 0 && (
            <div>
              <h3 className="font-medium text-foreground">Actionable Tips</h3>
              <ul className="mt-2 space-y-2">
                {scorecard.actionable_tips.map((tip: string, index: number) => (
                  <li key={index} className="flex items-start gap-2 text-sm text-muted-foreground">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                    {tip}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {qaQuestion ? (
            <Button onClick={() => setShowQa(true)} className="w-full">
              Continue to Audience Q&A
            </Button>
          ) : (
            <Button onClick={() => router.push("/dashboard/public-speaking")} className="w-full">
              Try Another Speech Type
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function ScoreCard({ label, score }: { label: string; score: number }) {
  const getColor = (score: number) => {
    if (score >= 80) return "text-success";
    if (score >= 60) return "text-warning";
    return "text-danger";
  };

  return (
    <div className="rounded-lg bg-muted/50 p-4 text-center">
      <div className="text-2xl font-bold text-foreground">{score}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}