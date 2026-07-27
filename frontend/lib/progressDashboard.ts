import { api } from "./api";

export interface PrimaryMetric {
  name: string;
  value: number;
  unit: string;
  is_primary: boolean;
  description: string;
}

export interface TrendPoint {
  date: string;
  confidence_score?: number | null;
  fluency_score?: number | null;
  vocabulary_score?: number | null;
  pronunciation_score?: number | null;
  practice_time_minutes: number;
}

export interface ProgressDashboardMetrics {
  confidence_score: PrimaryMetric;
  fluency_score?: number | null;
  vocabulary_score?: number | null;
  pronunciation_score?: number | null;
  total_practice_time_minutes: number;
  total_practice_time_hours: number;
  completed_sessions_count: number;
  vocabulary_growth_count: number;
  daily_streak_days: number;
}

export interface ProgressDashboardData {
  user_id: string;
  generated_at: string;
  sync_status: "synced" | "stale";
  is_stale: boolean;
  is_empty_state: boolean;
  empty_state_prompt?: string | null;
  primary_metric: PrimaryMetric;
  summary_metrics: ProgressDashboardMetrics;
  trend_lines: TrendPoint[];
  flagged_outliers_count: number;
  sync_message?: string | null;
}

export function getProgressDashboard() {
  return api<ProgressDashboardData>("/progress-dashboard/progress");
}

// Retain legacy interface for overview
export interface VocabularyGrowth {
  new_words_count: number;
  new_words?: string[];
  is_empty_state: boolean;
  is_zero_growth: boolean;
  message: string | null;
}

export interface VocabularyHistoryPoint {
  date: string;
  vocabulary_score: number;
}

export interface ProgressDashboardOverview {
  has_data: boolean;
  generated_at: string;
  metrics: {
    practice_time_minutes: number;
    confidence_score: number | null;
    fluency_score: number | null;
    vocabulary_score: number | null;
  };
  vocabulary_growth: VocabularyGrowth;
  vocabulary_history: VocabularyHistoryPoint[];
}

export function getProgressDashboardOverview() {
  return api<ProgressDashboardOverview>("/progress-dashboard/overview");
}
