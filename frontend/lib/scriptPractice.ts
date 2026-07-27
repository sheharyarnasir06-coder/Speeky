import { api } from "./api";

// Script Practice Confidence Score — US-157 / PSA-US-05

export interface ReadMetrics {
  confidence: number;
  fluency: number;
  vocabulary: number;
  pronunciation: number | null;
}

export interface StartPracticeResult {
  session_id: string;
  status: string;
}

export interface BaselineResult {
  session_id: string;
  baseline_confidence: number;
  metrics: ReadMetrics;
  status: string;
}

export interface AfterResult {
  session_id: string;
  baseline_confidence: number;
  after_confidence: number;
  confidence_gain: number;
  improved: boolean;
  baseline_metrics: ReadMetrics;
  after_metrics: ReadMetrics;
  feedback: string;
  history_id: string;
  status: string;
}

export interface HistoryEntry {
  id: string;
  script: string;
  context?: string | null;
  baseline_confidence: number;
  after_confidence: number;
  confidence_gain: number;
  baseline_metrics: ReadMetrics;
  after_metrics: ReadMetrics;
  feedback?: string | null;
  created_at: string;
}

export interface PaginatedHistory {
  entries: HistoryEntry[];
  total: number;
  offset: number;
  limit: number;
  completed_count: number;
  average_gain?: number | null;
}

export function startPractice(script: string, context?: string) {
  return api<StartPracticeResult>("/script-practice/start", {
    method: "POST",
    body: JSON.stringify({ script, context: context ?? null }),
  });
}

export function submitBaseline(sessionId: string, transcript: string, durationSeconds: number) {
  return api<BaselineResult>(`/script-practice/${sessionId}/baseline`, {
    method: "POST",
    body: JSON.stringify({ transcript, duration_seconds: durationSeconds }),
  });
}

export function submitAfter(sessionId: string, transcript: string, durationSeconds: number) {
  return api<AfterResult>(`/script-practice/${sessionId}/after`, {
    method: "POST",
    body: JSON.stringify({ transcript, duration_seconds: durationSeconds }),
  });
}

// Server-side paginated history (newest first).
export function getPracticeHistory(offset = 0, limit = 5) {
  return api<PaginatedHistory>(
    `/script-practice/history?offset=${offset}&limit=${limit}`,
  );
}
