import { api } from "./api";

export type ExploreFeature = "conversation" | "scenario" | "coaching" | "interview_coach";

export interface OpenExploreSession {
  active: boolean;
  feature?: ExploreFeature;
  session_id?: string;
  scenario_key?: string;
  label?: string | null;
  resume_path?: string;
  started_at?: string;
}

export function getOpenExploreSession() {
  return api<OpenExploreSession>("/active-sessions/explore");
}

// The banner's "X" — actually ends whatever's open (same effect a fresh start
// already has) instead of just hiding the UI, so it stops coming back.
export function dismissOpenExploreSession() {
  return api<{ dismissed: boolean }>("/active-sessions/explore/dismiss", { method: "POST" });
}

export interface ResumablePublicSpeaking {
  found: boolean;
  session_id?: string;
  speech_type?: string;
  label?: string;
  started_at?: string;
}

export function getResumablePublicSpeaking() {
  return api<ResumablePublicSpeaking>("/public-speaking/resume");
}
