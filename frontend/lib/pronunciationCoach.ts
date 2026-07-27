import { api } from "./api";

// US-74 (engine outage/timeout fallback), US-75 (cross-session trouble
// words), US-76 (accessibility safeguard), US-79 (word-level highlighting).
// All four share one backend scoring call (see
// backend/services/pronunciation_coach_service.py) — this file mirrors
// that: one scoreConversationTurn() call, one shape of result reused by
// every UI surface.

export type ColorTier = "green" | "orange" | "red" | "gray" | "unscorable";

export interface WordScoreResult {
  index: number;
  target_word: string;
  tier: ColorTier;
  strikethrough: boolean;
  final_score: number | null;
  raw_confidence_pct: number | null;
  note: string;
}

export interface SentenceScoreResult {
  target_sentence: string;
  fluency_score: number;
  scoring_profile: "standard" | "accessibility";
  retry_recommended: boolean;
  words: WordScoreResult[];
}

export interface ScoreTurnResponse {
  status: "scored" | "retrying" | "outage_queued" | "hard_failure" | "corrupted_discarded";
  message: string | null;
  result?: SentenceScoreResult;
}

export function scoreConversationTurn(sessionId: string, turnIndex: number) {
  return api<ScoreTurnResponse>(`/pronunciation-coach/sessions/${sessionId}/turns/${turnIndex}/score`, {
    method: "POST",
  });
}

export function getConversationTurnScore(sessionId: string, turnIndex: number) {
  return api<SentenceScoreResult>(`/pronunciation-coach/sessions/${sessionId}/turns/${turnIndex}/score`);
}

// US-76: accessibility safeguard
export interface AccessibilityProfile {
  opted_in: boolean;
  disclosed_condition: string | null;
}

export function getAccessibilityProfile() {
  return api<AccessibilityProfile>("/pronunciation-coach/accessibility-profile");
}

export function updateAccessibilityProfile(data: { opted_in: boolean; disclosed_condition?: string | null }) {
  return api<AccessibilityProfile>("/pronunciation-coach/accessibility-profile", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// US-75: cross-session trouble words bank & spaced repetition
export interface TroubleWordEntry {
  pattern_key: string;
  display_word: string;
  fail_session_count: number;
  correct_session_count: number;
  related_words: string[];
  status: "candidate" | "active" | "mastered";
  manually_dismissed: boolean;
  last_updated: string;
}

export function getActiveTroubleWords() {
  return api<{ words: TroubleWordEntry[] }>("/pronunciation-coach/trouble-words");
}

export function getTroubleWordsArchive() {
  return api<{ words: TroubleWordEntry[] }>("/pronunciation-coach/trouble-words/archive");
}

export function dismissTroubleWord(patternKey: string) {
  return api<{ pattern_key: string; dismissed: boolean }>(
    `/pronunciation-coach/trouble-words/${encodeURIComponent(patternKey)}/dismiss`,
    { method: "POST" }
  );
}
