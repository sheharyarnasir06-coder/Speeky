import { api } from "./api";
import type { MetricKey } from "./adminAlerts";

// GAP-06 (US-204): Period-over-Period Comparative Analysis.

export type ComparisonBasis = "WoW" | "MoM" | "YoY";

export const BASIS_LABELS: Record<ComparisonBasis, string> = {
  WoW: "Week over Week",
  MoM: "Month over Month",
  YoY: "Year over Year",
};

export interface ComparisonResponse {
  metric_key: string;
  metric_label: string;
  basis: ComparisonBasis;
  current_start: string;
  current_end: string;
  prior_start: string;
  prior_end: string;
  current_value: number;
  prior_value: number;
  pct_change: number | null;
  direction: "up" | "down" | "flat" | "new";
  is_new: boolean;
  day_count_mismatch: boolean;
  outage_flagged: boolean;
  outage_note: string | null;
}

export interface AvailableBasesResponse {
  available: ComparisonBasis[];
  launch_date: string;
  days_of_history: number;
}

export interface Incident {
  id: string;
  label: string;
  start_at: string;
  end_at: string;
}

export function getComparison(metric: MetricKey, basis: ComparisonBasis) {
  return api<ComparisonResponse>(`/analytics/comparison?metric=${metric}&basis=${basis}`);
}

export function getAvailableBases() {
  return api<AvailableBasesResponse>("/analytics/comparison/available-bases");
}

export function listIncidents() {
  return api<{ incidents: Incident[] }>("/analytics/incidents");
}

export function addIncident(data: { label: string; start_at: string; end_at: string }) {
  return api<Incident>("/analytics/incidents", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
