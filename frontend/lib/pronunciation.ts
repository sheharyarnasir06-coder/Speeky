import { api, API_URL, ApiError } from "./api";

// ── Pronunciation Coach API (prefix: /api/pronunciation-coach) ──────────────
// Mirrors backend/schemas/pronunciation_schemas.py response shapes exactly.

export interface WordClassification {
  word: string;
  target_index: number;
  status: "correct" | "stress_error" | "mispronounced" | "skipped";
  confidence?: number | null;
}

export interface PronunciationSession {
  session_id: string;
  status: "active" | "interrupted" | "completed";
  phoneme: string;
  phoneme_tag: string;
  sentence: string;
  message?: string | null;
  started_at?: string;
}

export interface AttemptResult {
  session_id: string;
  message_key: string;
  message: string;
  words: WordClassification[];
  transcript?: string;
  next_sentence?: string | null;
  next_phoneme?: string | null;
  next_phoneme_tag?: string | null;
  // ACC-US-11/ACC-US-09: which accent model actually scored this attempt, and any
  // calibration-fallback warning (e.g. local model unavailable) to surface to the user.
  accent_profile?: string | null;
  warning?: string | null;
  model_used?: string | null;
}

// Structured rejection body (422/403) for ACC-US-01 liveness/playback-audio checks —
// same shape the one-shot Pronunciation Coach and Accent Assessment both return.
export interface RecordingRejected {
  status: "rejected";
  reason: string;
  message: string;
  appeal_token?: string | null;
  appeal_prompt?: string | null;
}

export interface RetryResult {
  session_id: string;
  message: string;
  frustration_breakdown: boolean;
  transcript?: string;
}

export interface ResumeCheck {
  found: boolean;
  session_id?: string | null;
  message: string;
  stale: boolean;
}

export interface ResumeResult {
  session_id: string;
  status: "active" | "interrupted" | "completed";
  phoneme: string;
  phoneme_tag: string;
  sentence: string;
  message: string;
}

export interface PhonemeAccuracy {
  phoneme: string;
  attempts: number;
  correct_words: number;
  total_words: number;
}

export interface SessionSummary {
  session_id: string;
  status: string;
  attempt_count: number;
  phoneme_accuracy: PhonemeAccuracy[];
  ended_at: string;
}

function getDeviceId(): string {
  if (typeof window === "undefined") return "server";
  const key = "speeky:pronunciation-device-id";
  let id = window.localStorage.getItem(key);
  if (!id) {
    id = `web_${Math.random().toString(36).slice(2)}_${Date.now()}`;
    window.localStorage.setItem(key, id);
  }
  return id;
}

export function startPronunciationSession() {
  return api<PronunciationSession>("/pronunciation-coach/start", {
    method: "POST",
    body: JSON.stringify({ device_id: getDeviceId() }),
  });
}

export function submitAttempt(sessionId: string, audio: Blob) {
  const form = new FormData();
  form.append("audio", audio, "attempt.webm");
  return api<AttemptResult>(`/pronunciation-coach/${sessionId}/attempt`, {
    method: "POST",
    body: form,
  });
}

export function retryWord(sessionId: string, targetWord: string, audio: Blob) {
  const form = new FormData();
  form.append("target_word", targetWord);
  form.append("audio", audio, "retry.webm");
  return api<RetryResult>(`/pronunciation-coach/${sessionId}/retry`, {
    method: "POST",
    body: form,
  });
}

export function interruptSession(sessionId: string) {
  return api<{ session_id: string; status: string; message: string }>(
    `/pronunciation-coach/${sessionId}/interrupt`,
    { method: "POST" }
  );
}

export function checkResumableSession() {
  return api<ResumeCheck>("/pronunciation-coach/resume");
}

export function resumeSession(sessionId: string) {
  return api<ResumeResult>(`/pronunciation-coach/${sessionId}/resume`, {
    method: "POST",
    body: JSON.stringify({ device_id: getDeviceId() }),
  });
}

export function endSession(sessionId: string) {
  return api<SessionSummary>(`/pronunciation-coach/${sessionId}/end`, { method: "POST" });
}

// GET /api/pronunciation-coach/words/{word}/audio?speed=normal|slow — returns a
// raw audio/wav body on success (not JSON), so this fetches manually rather
// than through the api() JSON helper (mirrors lib/conversation.ts's synthesizeSpeech).
// Standalone (PRN-US-10/PRN-US-11): no session state needed, unchanged from the
// original one-shot Pronunciation Coach.
export async function fetchPronunciationTts(
  word: string,
  speed: "normal" | "slow" = "normal"
): Promise<Blob> {
  const response = await fetch(
    `${API_URL}/pronunciation-coach/words/${encodeURIComponent(word)}/audio?speed=${speed}`,
    { credentials: "include" }
  );
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(data?.error ?? "Correct pronunciation audio unavailable", response.status, data);
  }
  return response.blob();
}

/** Reads the structured RecordingRejectedSchema body off a 422/403 ApiError, if present. */
export function rejectionFromError(err: unknown): RecordingRejected | null {
  if (!(err instanceof ApiError) || !err.body || typeof err.body !== "object") {
    return null;
  }
  const body = err.body as Partial<RecordingRejected>;
  if (typeof body.message !== "string" || typeof body.reason !== "string") return null;
  return {
    status: "rejected",
    reason: body.reason,
    message: body.message,
    appeal_token: body.appeal_token ?? null,
    appeal_prompt: body.appeal_prompt ?? null,
  };
}
