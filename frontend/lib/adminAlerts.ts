import { api } from "./api";

// GAP-03 (US-201): Anomaly Detection & Proactive Alerting.

export type MetricKey = "daily_signups" | "day1_retention" | "day7_retention" | "churn_rate" | "active_users" | "revenue";
export type ThresholdType = "stddev_multiplier" | "percent_change" | "absolute";
export type ThresholdDirection = "above" | "below" | "any";
export type AlertChannel = "email" | "slack" | "push";
export type AlertStatus = "open" | "acknowledged" | "false_positive" | "resolved";

export const METRIC_OPTIONS: { value: MetricKey; label: string }[] = [
  { value: "daily_signups", label: "Daily Signups" },
  { value: "day1_retention", label: "Day-1 Retention" },
  { value: "day7_retention", label: "Day-7 Retention" },
  { value: "churn_rate", label: "Churn Rate" },
  { value: "active_users", label: "Active Users" },
  { value: "revenue", label: "Revenue" },
];

export interface MetricThreshold {
  id: string;
  metric_key: MetricKey;
  owner_admin_id: string;
  threshold_type: ThresholdType;
  threshold_value: number;
  direction: ThresholdDirection;
  channels: AlertChannel[];
  slack_webhook_url: string | null;
  is_active: boolean;
}

export interface AnomalyAlert {
  id: string;
  metric_key: MetricKey;
  metric_label: string;
  value: number;
  baseline_value: number;
  deviation: number;
  status: AlertStatus;
  digest_group_id: string | null;
  is_unassigned: boolean;
  incident_key: string;
  deep_link_path: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
}

export function listThresholds(metricKey?: string) {
  const query = metricKey ? `?metric_key=${encodeURIComponent(metricKey)}` : "";
  return api<{ thresholds: MetricThreshold[] }>(`/alerts/thresholds${query}`);
}

export function upsertThreshold(data: {
  metric_key: MetricKey;
  owner_admin_id?: string;
  threshold_type: ThresholdType;
  threshold_value: number;
  direction: ThresholdDirection;
  channels: AlertChannel[];
  slack_webhook_url?: string | null;
}) {
  return api<{ threshold: MetricThreshold }>("/alerts/thresholds", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deactivateThreshold(thresholdId: string) {
  return api<{ deactivated: boolean }>(`/alerts/thresholds/${thresholdId}`, { method: "DELETE" });
}

export function listAlerts(params: { status?: string; metric_key?: string } = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.metric_key) query.set("metric_key", params.metric_key);
  const qs = query.toString();
  return api<{ alerts: AnomalyAlert[] }>(`/alerts/${qs ? `?${qs}` : ""}`);
}

export function acknowledgeAlert(alertId: string) {
  return api<{ alert: AnomalyAlert }>(`/alerts/${alertId}/acknowledge`, { method: "POST" });
}

export function markFalsePositive(alertId: string) {
  return api<{ alert: AnomalyAlert }>(`/alerts/${alertId}/false-positive`, { method: "POST" });
}

export function listUnassignedAlerts() {
  return api<{ alerts: AnomalyAlert[] }>("/alerts/unassigned");
}

export function assignUnassignedAlert(alertId: string, ownerAdminId: string) {
  return api<{ alert: AnomalyAlert }>(`/alerts/${alertId}/assign-owner`, {
    method: "POST",
    body: JSON.stringify({ owner_admin_id: ownerAdminId }),
  });
}

// Dev-only manual trigger (disabled server-side in production).
export function triggerDetectionNow() {
  return api<{ run_id: string; breaches: number }>("/alerts/dev-trigger", { method: "POST" });
}
