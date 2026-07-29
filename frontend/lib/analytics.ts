import { api, API_URL, ApiError } from "./api";

export interface DailyPoint {
  date: string;
  count: number;
}

export interface FunnelStep {
  step: string;
  count: number;
  pct_of_start: number;
  drop_off_pct: number;
}

export interface FeatureUsageRow {
  key: string;
  label: string;
  category: string;
  started: number;
  completed: number;
  completion_rate: number;
  new: boolean;
  archived: boolean;
}

export interface OverviewResult {
  computed_at: string;
  period_days: number;
  active_users: number;
  daily_sessions: DailyPoint[];
  retention_rate: number | null;
  top_feature_usage: FeatureUsageRow[];
  onboarding_funnel: FunnelStep[];
  zero_data: boolean;
}

export interface FunnelResult {
  computed_at: string;
  period_days: number;
  funnel: FunnelStep[];
  zero_data: boolean;
}

export interface FeatureUsageResult {
  computed_at: string;
  period_days: number;
  show_archived: boolean;
  features: FeatureUsageRow[];
  zero_data: boolean;
}

export type CrossFilterFeature =
  | "scenario_based_learning"
  | "workplace_coaching"
  | "public_speaking"
  | "pronunciation_coach"
  | "accent_assessment";

export const CROSS_FILTER_FEATURES: { value: CrossFilterFeature; label: string }[] = [
  { value: "scenario_based_learning", label: "Scenario-Based Learning" },
  { value: "workplace_coaching", label: "Workplace English Coach" },
  { value: "public_speaking", label: "Public Speaking Coach" },
  { value: "pronunciation_coach", label: "Pronunciation Coach" },
  { value: "accent_assessment", label: "Accent Assessment" },
];

export interface RetentionGroup {
  cohort_size: number;
  retention_rate: number | null;
}

export interface CrossFilterResult {
  feature: string;
  feature_label: string;
  zero_data: boolean;
  engaged: RetentionGroup | null;
  general: RetentionGroup | null;
  computed_at?: string;
  period_days?: number;
  status?: "processing";
  message?: string;
}

export interface CohortRetentionRow {
  cohort: string;
  day1: number;
  day7: number;
  day30: number | null;
}

export interface RevenueResult {
  mock: true;
  note: string;
  computed_at: string;
  period_days: number;
  currency: string;
  mrr_series: { date: string; mrr: number }[];
  current_mrr: number;
  churn_rate_pct: number;
  cohort_retention: CohortRetentionRow[];
}

export function getOverview(days: number) {
  return api<OverviewResult>(`/analytics/overview?days=${days}`);
}

export function getFunnel(days: number) {
  return api<FunnelResult>(`/analytics/funnel?days=${days}`);
}

export function getFeatureUsage(days: number, showArchived: boolean) {
  return api<FeatureUsageResult>(`/analytics/feature-usage?days=${days}&show_archived=${showArchived}`);
}

export function getRetentionByFeature(days: number, feature: CrossFilterFeature) {
  return api<CrossFilterResult>(`/analytics/retention-by-feature?days=${days}&feature=${feature}`);
}

export function getRevenue(days: number) {
  return api<RevenueResult>(`/analytics/revenue?days=${days}`);
}

// CSV exports return text/csv, not JSON, so they bypass the JSON-typed api<T>
// helper — fetch directly (same credentials/base-URL convention), then trigger a
// client-side download via a throwaway object URL. Cross-origin cookie auth is
// carried automatically by fetch with credentials:"include", same as everywhere
// else in this app; no need for a raw <a href> navigation.
async function downloadCsv(endpoint: string, filename: string): Promise<void> {
  const response = await fetch(`${API_URL}${endpoint}`, { credentials: "include" });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const message = (data && typeof data === "object" && "error" in data && typeof data.error === "string")
      ? data.error
      : "Export failed";
    throw new ApiError(message, response.status, data);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function exportFunnelCsv(days: number) {
  return downloadCsv(`/analytics/funnel/export?days=${days}`, "funnel.csv");
}

export function exportFeatureUsageCsv(days: number, showArchived: boolean) {
  return downloadCsv(`/analytics/feature-usage/export?days=${days}&show_archived=${showArchived}`, "feature_usage.csv");
}

export function exportRetentionByFeatureCsv(days: number, feature: CrossFilterFeature) {
  return downloadCsv(`/analytics/retention-by-feature/export?days=${days}&feature=${feature}`, "retention_by_feature.csv");
}
