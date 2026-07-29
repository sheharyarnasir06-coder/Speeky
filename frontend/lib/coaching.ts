import { api } from "./api";
import type { VoiceTokenResult } from "./useLiveKitVoice";

export interface CoachingScenarioMeta {
  key: string;
  label: string;
  story: string;
  default_input_mode: "text" | "audio";
  roleplay: boolean;
  example_prompts: string[];
}

export interface StartCoachingResult {
  session_id: string;
  scenario: string;
  label: string;
  input_mode: "text" | "audio";
  roleplay: boolean;
  prompt: string;
  opening_message?: string;
}

export interface CoachingFlag {
  type: string;
  phrase?: string;
  message?: string;
  suggestion?: string;
}

export interface CoachingResult {
  session_id: string;
  status: string;
  input_mode: "text" | "audio";
  scores: {
    professional_tone: number | null;
    clarity: number | null;
    effectiveness: number | null;
    fluency: number | null;
    vocabulary: number | null;
    pronunciation: number | null;
    confidence: number | null;
  };
  headline_metric: string;
  met_objective: boolean;
  flags: CoachingFlag[];
  highlights: { kind: string; phrase: string }[];
  polished_version: string;
  summary: string;
  graded_by: string;
}

export interface RoleplayTurnResult {
  session_id: string;
  reply: string;
  status: string;
  ended_early: boolean;
  transcript: string;
}

export function getCoachingScenarios() {
  return api<{ scenarios: CoachingScenarioMeta[] }>("/coaching/scenarios");
}

export function startCoachingSession(data: {
  scenario: string;
  input_mode?: string;
  prompt?: string;
}) {
  return api<StartCoachingResult>("/coaching/start", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function submitCoachingSession(
  sessionId: string,
  data: {
    submission?: string;
    subject?: string;
    audio_features?: { transcript: string; duration_seconds: number };
  }
) {
  return api<CoachingResult>(`/coaching/${sessionId}/submit`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getCoachingVoiceToken(sessionId: string) {
  return api<VoiceTokenResult>(`/coaching/${sessionId}/voice-token`, {
    method: "POST",
  });
}

export function sendRoleplayTurn(sessionId: string, message: string) {
  return api<RoleplayTurnResult>(`/coaching/${sessionId}/turn`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function getCoachingSession(sessionId: string) {
  return api<CoachingResult & { prompt: string; submission: string | null }>(
    `/coaching/${sessionId}`
  );
}

// Raw session state — used to resume an in-progress roleplay (the ?resume= query
// param flow), where the caller needs the actual turns, not the graded-result shape
// getCoachingSession() above returns (only meaningful once a session is COMPLETED).
export interface CoachingSessionState {
  session_id: string;
  scenario: string;
  label: string;
  roleplay: boolean;
  turns: { role: "user" | "assistant"; content: string }[];
  input_mode: "text" | "audio";
  status: string;
  prompt: string;
  submission: string | null;
}

export function getCoachingSessionState(sessionId: string) {
  return api<CoachingSessionState>(`/coaching/${sessionId}`);
}
