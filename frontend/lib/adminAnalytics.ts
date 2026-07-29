import { api } from "./api";
import type { MetricKey } from "./adminAlerts";

export interface MetricPoint {
  date: string; // YYYY-MM-DD
  value: number;
}

export interface MetricSeries {
  label: string;
  available: boolean; // false for "revenue" — no billing pipeline exists yet
  points: MetricPoint[];
}

export interface DashboardSnapshot {
  metrics: Record<MetricKey, MetricSeries>;
  date_from: string;
  date_to: string;
}

export function getSnapshot(metrics: MetricKey[], dateFrom?: string, dateTo?: string) {
  const query = new URLSearchParams({ metrics: metrics.join(",") });
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);
  return api<DashboardSnapshot>(`/analytics/snapshot?${query.toString()}`);
}
