import { api } from "./api";

// ── Filler Word API (prefix: /api/public-speaking) ───────────────────────────
// Routes from: backend/routers/public_speaking_routes.py
// GET /api/public-speaking/{session_id}/filler-words

export interface FillerWordMarker {
  word: string;
  start_time?: number | null;
  end_time?: number | null;
  position: number;
  confidence: number;
  category: string;
}

export interface FillerWordFrequency {
  word: string;
  count: number;
}

export interface FillerWordAnalysisResponse {
  session_id: string;
  speech_type?: string | null;
  total_filler_count: number;
  flawless_delivery: boolean;
  badge?: string | null;
  filler_frequencies: Record<string, number>;
  filler_counts: FillerWordFrequency[];
  timeline_markers: FillerWordMarker[];
  actionable_tip: string;
  analysis_summary: string;
}

// GET /api/public-speaking/{session_id}/filler-words
export function getPublicSpeakingFillerWords(sessionId: string) {
  return api<FillerWordAnalysisResponse>(`/public-speaking/${sessionId}/filler-words`);
}

// GET /api/interview-coach/sessions/{session_id}/filler-words
// Route from: backend/routers/interview_coach_routes.py
export function getInterviewCoachFillerWords(sessionId: string) {
  return api<FillerWordAnalysisResponse>(`/interview-coach/sessions/${sessionId}/filler-words`);
}
