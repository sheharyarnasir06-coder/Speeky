import { api } from "./api";

// ── Accent Progress Tracker (prefix: /api/accent-assessment) ─────────────────
// Routes from: backend/routers/accent_routes.py
// GET /api/accent-assessment/progress-tracker

export interface MonthMetric {
  month: number;
  pronunciation: number | null;
  word_stress: number | null;
  intonation: number | null;
  clarity: number | null;
  is_locked: boolean;
}

export interface AccentProgressTrackerData {
  is_insufficient_data: boolean;
  message?: string | null;
  cta_suggestion?: string | null;
  regressed_metrics: string[];
  months: MonthMetric[];
}

// GET /api/accent-assessment/progress-tracker
export function getAccentProgressTracker() {
  return api<AccentProgressTrackerData>("/accent-assessment/progress-tracker");
}

// ── Legacy: Accent Progress Matrix (prefix: /api/accent-progress) ────────────
// Routes from: backend/routers/accent_progress_routes.py
// GET /api/accent-progress/matrix

export type AccentTrend = "improved" | "stagnated" | "degraded";

export interface AccentMetricRow {
  key: string;
  label: string;
  month1_score: number;
  month3_score: number | null;
  trend: AccentTrend | null;
  tune_up_prompt: string | null;
}

export interface AccentProgressMatrix {
  has_baseline: boolean;
  force_baseline: boolean;
  message?: string;
  locked?: boolean;
  days_until_unlock?: number | null;
  /** Server-built lock copy — correct wording whether the wait is days away or the
   *  Month 3 check-in is simply outstanding. Falls back to the day count if absent. */
  unlock_message?: string | null;
  baseline_completed_at?: string;
  current_completed_at?: string | null;
  metrics?: AccentMetricRow[];
}

export interface SubmitAccentAssessmentInput {
  pronunciation_score: number;
  word_stress_score: number;
  intonation_score: number;
  clarity_score: number;
}

export interface SubmitAccentAssessmentResult {
  assessment_id: string;
  month_index: number;
  completed_at: string;
  is_baseline: boolean;
}

// GET /api/accent-progress/matrix
export function getAccentProgressMatrix() {
  return api<AccentProgressMatrix>("/accent-progress/matrix");
}

// POST /api/accent-progress/assessments
export function submitAccentAssessment(data: SubmitAccentAssessmentInput) {
  return api<SubmitAccentAssessmentResult>("/accent-progress/assessments", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
