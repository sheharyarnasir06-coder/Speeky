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

// ── US-205 Audit Log Types ──────────────────────────────────────────────────
export interface AuditLogEntry {
  id: string;
  actor_id: string;
  actor_role: string;
  timestamp: string;
  action_type: string;
  module: string;
  scope: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
}

export interface AuditLogListResponse {
  entries: AuditLogEntry[];
  total: number;
  tamper_detected: boolean;
}

export interface AuditLogVerifyResponse {
  chain_intact: boolean;
  checked_at: string;
}

export interface ExportDataResponse {
  export_id: string;
  module: string;
  scope: Record<string, unknown>;
  content: string;
  audit_entry_id: string;
  timestamp: string;
}

// ── US-206 Custom Dashboard Views Types ─────────────────────────────────────
export interface DashboardWidgetConfig {
  id: string;
  position?: number;
  settings?: Record<string, unknown>;
}

export interface SavedViewCreateRequest {
  name: string;
  widgets: DashboardWidgetConfig[];
  filters?: Record<string, unknown>;
  is_shared?: boolean;
  overwrite?: boolean;
}

export interface SavedViewResponse {
  id: string;
  user_id: string;
  name: string;
  widgets: Array<Record<string, unknown>>;
  filters: Record<string, unknown>;
  is_shared: boolean;
  warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface SavedViewListResponse {
  views: SavedViewResponse[];
}

// ── US-207 Cross-Source Data Reconciliation Types ────────────────────────────
export interface MismatchedItem {
  user_id: string;
  delta: number;
  renewal_at?: string | null;
  transaction_id?: string;
  [key: string]: unknown;
}

export interface ReconciliationProviderResult {
  provider: string;
  internal_count: number;
  internal_revenue: number;
  provider_count: number;
  provider_revenue: number;
  variance_pct: number;
  status: string; // "RECONCILED" | "DISCREPANCY_DETECTED" | "RECONCILIATION_PENDING"
  grace_applied_count: number;
  mismatched_items: MismatchedItem[];
}

export interface ReconciliationSummaryResponse {
  status: string; // "RECONCILED" | "DISCREPANCY_DETECTED" | "RECONCILIATION_PENDING"
  computed_at: string;
  tolerance_pct: number;
  providers: Record<string, ReconciliationProviderResult>;
  pending: boolean;
  retry_count: number;
  message?: string | null;
}

export interface TargetedResyncRequest {
  user_id: string;
  transaction_id: string;
  provider: string;
  reason?: string;
}

export interface TargetedResyncResponse {
  resynced: boolean;
  user_id: string;
  transaction_id: string;
  provider: string;
  updated_internal_revenue: number;
  message: string;
}

// ── Analytics Core API Calls ─────────────────────────────────────────────────

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

// ── US-205 Audit Log API Calls ───────────────────────────────────────────────

export function getAuditLogs(params?: {
  actor_id?: string;
  action_type?: string;
  date_from?: string;
  date_to?: string;
}) {
  const queryParams = new URLSearchParams();
  if (params?.actor_id) queryParams.set("actor_id", params.actor_id);
  if (params?.action_type) queryParams.set("action_type", params.action_type);
  if (params?.date_from) queryParams.set("date_from", params.date_from);
  if (params?.date_to) queryParams.set("date_to", params.date_to);

  const qs = queryParams.toString();
  return api<AuditLogListResponse>(`/analytics/audit-logs${qs ? `?${qs}` : ""}`);
}

export function verifyAuditLogIntegrity() {
  return api<AuditLogVerifyResponse>("/analytics/audit-logs/verify");
}

export async function exportAuditLoggedData(
  module: string,
  filters: Record<string, unknown> = {},
  export_format: string = "csv",
  filename?: string
): Promise<ExportDataResponse> {
  const res = await api<ExportDataResponse>("/analytics/export", {
    method: "POST",
    body: JSON.stringify({ module, filters, export_format }),
  });

  // Fail-closed client behavior: if api call succeeded, trigger download of logged output
  const blob = new Blob([res.content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || `${module.toLowerCase().replace(/\s+/g, "_")}_export.csv`;
  link.click();
  URL.revokeObjectURL(url);

  return res;
}

// Legacy CSV exports fallback
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
  return exportAuditLoggedData("Funnel", { days }, "csv", "funnel.csv");
}

export function exportFeatureUsageCsv(days: number, showArchived: boolean) {
  return exportAuditLoggedData("FeatureUsage", { days, showArchived }, "csv", "feature_usage.csv");
}

export function exportRetentionByFeatureCsv(days: number, feature: CrossFilterFeature) {
  return exportAuditLoggedData("RetentionByFeature", { days, feature }, "csv", "retention_by_feature.csv");
}

// ── US-206 Custom Dashboard Views API Calls ──────────────────────────────────

export function getSavedViews() {
  return api<SavedViewListResponse>("/analytics/views");
}

export function getSavedView(viewId: string) {
  return api<SavedViewResponse>(`/analytics/views/${viewId}`);
}

export function createSavedView(data: SavedViewCreateRequest) {
  return api<SavedViewResponse>("/analytics/views", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deleteSavedView(viewId: string) {
  return api<{ deleted: boolean; view_id: string }>(`/analytics/views/${viewId}`, {
    method: "DELETE",
  });
}

// ── US-207 Data Reconciliation API Calls ─────────────────────────────────────

export function getReconciliationStatus() {
  return api<ReconciliationSummaryResponse>("/analytics/reconciliation/status");
}

export function runReconciliationJob() {
  return api<ReconciliationSummaryResponse>("/analytics/reconciliation/run", {
    method: "POST",
  });
}

export function resyncUserRecord(data: TargetedResyncRequest) {
  return api<TargetedResyncResponse>("/analytics/reconciliation/resync", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
