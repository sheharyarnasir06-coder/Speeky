import { api } from "./api";
import type { ScoredVideo, VideoFeatures, VideoTimeline } from "./vision/types";

// Public Speaking Coach — PSC-US-01/03/04/05/06/07/11/12/14.
// Backend routes live under /public-speaking (see backend/main.py include_router
// prefix "/api/public-speaking"); api() prepends the backend origin + /api and
// sends the auth cookie, so these must NOT be called with a bare relative fetch.

/** "audio_video" is voice PLUS an opted-in camera. There is no video-only mode: physical
 *  delivery is only ever scored alongside a spoken turn. */
export type PublicSpeakingInputMode = "audio" | "text" | "audio_video";

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
  input_mode: PublicSpeakingInputMode;
  structure_elements: string[];
  ideal_wpm_range: [number, number];
  /** Whether this scenario runs an audience Q&A after the speech. True for business_pitch,
   *  classroom and ted_talk; false for casual_event and motivational, where a follow-up
   *  question is a format error rather than a missing feature. */
  qa_enabled: boolean;
  topic: string | null;
  status: string;
}

/** Mirrors register_scorer.ScoredRegister.to_dict(). Each channel is a *match* score against
 *  the scenario's expected band, not a measurement: 100 means "this matched what a business
 *  pitch / wedding toast asks for", not "you were happy". */
export interface ScoredRegister {
  /** Vocal energy match, from pitch range, intensity variation and level. */
  voice_arousal: number | null;
  /** Facial warmth match, from smile percentage and expressiveness. Camera sessions only. */
  face_warmth: number | null;
  /** Word formality match, from a marker lexicon. Null under 20 words. */
  word_formality: number | null;
  emotional_register: number | null;
  /** 0-1, falling with the number of channels that had a source. */
  confidence_weight: number;
  issues: { type: string; message: string; suggestion?: string }[];
  highlights: { kind: string; message: string }[];
  detail: {
    arousal_raw: number | null;
    warmth_raw: number | null;
    formality_raw: number | null;
    expected: {
      arousal_band: [number, number] | null;
      smile_band: [number, number] | null;
      formality: string | null;
    };
    markers?: Record<string, unknown>;
    channels_measured: string[];
  };
}

export interface PublicSpeakingScorecard {
  speech_type: string;
  input_mode: string;
  /** Always "scored" here: delivery is measured from the audio and is real with or
   *  without the LLM. A failed topic check shows up as `topic_relevance: null`, not as an
   *  ungraded scorecard. */
  scoring_status: "scored";
  /** How well the transcript matched the session's chosen topic, 0-100. Null when the
   *  session had no topic or the judge could not run, in which case delivery scores stand
   *  on their own. Otherwise it scales overall_score. */
  topic_relevance: number | null;
  /** On a Q&A scenario this is the session total once the Q&A is answered: 70% speech,
   *  30% Q&A. `speech_only_score` holds the delivery half. */
  overall_score: number;
  confidence: number;
  /** overall_score before the Q&A was folded in. Null on rows scored before scoring_version 3. */
  speech_only_score: number | null;
  /** Populated once the Q&A is answered — the same numbers as SubmitQaResult.qa_score. */
  qa_handling: QaScore | null;
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
  /** Scenario-conditioned register match, 0-100 — how well the delivery's energy, warmth and
   *  formality matched what this kind of speech asks for. Never an emotion label; see
   *  backend/lib/register_scorer.py. Same value as `emotional_connection`, which is the older
   *  alias kept on the payload. */
  emotional_register: number | null;
  emotional_connection: number | null;
  /** register_scorer.ScoredRegister.to_dict(). Channels are null when their source was absent
   *  (no camera, text mode, transcript under 20 words). */
  register_detail: ScoredRegister | null;
  /** Camera sessions only. Deliberately NOT folded into overall_score — see
   *  backend/services/public_speaking_service.py::_generate_scorecard. */
  visual_presence: number | null;
  video: ScoredVideo | null;
  /** Per-second channels for the results sparklines. Echoed back from the submitted payload —
   *  the backend stores it but does not score from it. */
  video_timeline: VideoTimeline | null;
}

export interface SubmitTurnResult {
  scorecard: PublicSpeakingScorecard;
  qa_triggered: boolean;
  ai_question?: string;
  session_id: string;
}

export interface QaScore {
  /** Null when the grader was unavailable — the answer is saved but ungraded, and in that case
   *  it is deliberately NOT blended into overall_score. Must not be rendered as a 0. */
  composure: number | null;
  relevance: number | null;
  feedback: string;
}

export interface SubmitQaResult {
  qa_score: QaScore;
  updated_scorecard: PublicSpeakingScorecard;
  session_id: string;
}

export function startPublicSpeakingSession(body: {
  speech_type: SpeechType;
  input_mode: PublicSpeakingInputMode;
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
      snr_db?: number;
      mean_pitch_hz?: number;
      intensity_variation_db?: number;
    };
    /** Aggregated delivery metrics from the browser vision pipeline. No video, frames, or
     *  per-frame landmarks are ever uploaded. */
    video_features?: VideoFeatures | null;
    is_final: boolean;
  }
): Promise<SubmitTurnResult> {
  return api(`/public-speaking/${sessionId}/turn`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface PublicSpeakingSessionDetail {
  session_id: string;
  speech_type: string;
  input_mode: string;
  status: "in_progress" | "qa_phase" | "completed" | "abandoned";
  created_at: string;
  completed_at: string | null;
  topic: string | null;
  transcript: string | null;
  scorecard: PublicSpeakingScorecard | null;
  ai_question: string | null;
  user_qa_response: string | null;
  qa_score: QaScore | null;
}

/** Read a session back. Needed by the face-to-face Q&A: the *agent* submits and scores that
 *  answer server-side (backend/live_call/dispatch.py), so when the call ends the client has to
 *  fetch the result rather than submit again — the session is already "completed" by then, and
 *  a second POST /qa is refused with "This session is not in the Q&A phase." */
export function getPublicSpeakingSession(sessionId: string): Promise<PublicSpeakingSessionDetail> {
  return api(`/public-speaking/${sessionId}`);
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

