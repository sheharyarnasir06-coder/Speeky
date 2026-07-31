import { api } from "./api";

// Public Speaking Coach — PSC-US-01/03/04/05/06/07/11/12/14.
// Backend routes live under /public-speaking (see backend/main.py include_router
// prefix "/api/public-speaking"); api() prepends the backend origin + /api and
// sends the auth cookie, so these must NOT be called with a bare relative fetch.

export type SpeechType =
  | "business_pitch"
  | "casual_event"
  | "motivational"
  | "classroom"
  | "ted_talk";

export interface StartPublicSpeakingResult {
  session_id: string;
  speech_type: string;
  label: string;
  input_mode: "audio" | "text";
  structure_elements: string[];
  ideal_wpm_range: [number, number];
  topic: string | null;
  status: string;
}

export interface PublicSpeakingScorecard {
  speech_type: string;
  input_mode: string;
  overall_score: number;
  confidence: number;
  pacing: number | null;
  tone_variation: number;
  voice_clarity: number;
  structure: number;
  audience_engagement: number;
  words_per_minute: number | null;
  filler_word_count: number;
  filler_words: unknown[];
  flags: { type: string; message?: string; suggestion?: string }[];
  highlights: { kind: string; phrase: string }[];
  summary: string;
  actionable_tips: string[];
  delivery: Record<string, unknown> | null;
}

export interface SubmitTurnResult {
  scorecard: PublicSpeakingScorecard;
  qa_triggered: boolean;
  ai_question?: string;
  session_id: string;
}

export interface QaScore {
  composure: number;
  relevance: number;
  feedback: string;
}

export interface SubmitQaResult {
  qa_score: QaScore;
  updated_scorecard: PublicSpeakingScorecard;
  session_id: string;
}

export function startPublicSpeakingSession(body: {
  speech_type: SpeechType;
  input_mode: "audio" | "text";
  topic?: string | null;
}): Promise<StartPublicSpeakingResult> {
  return api("/public-speaking/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function submitPublicSpeakingTurn(
  sessionId: string,
  body: {
    audio_data?: string | null;
    text_content: string | null;
    duration_seconds?: number | null;
    audio_features?: {
      word_timings?: { word: string; start: number; end: number }[];
      avg_db?: number;
      pitch_range_semitones?: number;
      duration_seconds?: number;
    };
    is_final: boolean;
  }
): Promise<SubmitTurnResult> {
  return api(`/public-speaking/${sessionId}/turn`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function submitPublicSpeakingQa(
  sessionId: string,
  body: { audio_data?: string | null; text_content: string | null; duration_seconds?: number | null }
): Promise<SubmitQaResult> {
  return api(`/public-speaking/${sessionId}/qa`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

