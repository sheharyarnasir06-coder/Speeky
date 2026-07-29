import { api, ApiError } from "./api";
import type { MetricKey } from "./adminAlerts";

// GAP-04 (US-202): Scheduled Report Generation & Distribution.

export type DateRangeType = "last_7_days" | "last_30_days" | "month_to_date";
export type Recurrence = "weekly" | "monthly" | "none";
export type ReportFormat = "pdf" | "csv" | "both";
export type RecipientType = "internal" | "external";

export const DATE_RANGE_OPTIONS: { value: DateRangeType; label: string }[] = [
  { value: "last_7_days", label: "Last 7 days" },
  { value: "last_30_days", label: "Last 30 days" },
  { value: "month_to_date", label: "Month to date" },
];

export const RECURRENCE_OPTIONS: { value: Recurrence; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "none", label: "Manual only (no schedule)" },
];

// A representative sample — the picker also accepts any valid IANA name typed in.
export const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Karachi",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

export interface Recipient {
  type: RecipientType;
  value: string; // internal: admin User.id — external: email address
}

export interface ReportTemplate {
  id: string;
  name: string;
  owner_admin_id: string;
  metrics: MetricKey[];
  date_range_type: DateRangeType;
  recurrence: Recurrence;
  recurrence_day: number | null;
  recurrence_hour: number;
  recurrence_minute: number;
  timezone: string;
  recipients: Recipient[];
  format: ReportFormat;
  is_active: boolean;
  next_run_at: string | null;
  currently_generating: boolean;
  pending_schedule_update: Record<string, unknown> | null;
}

export interface ReportRun {
  id: string;
  template_id: string;
  status: "pending" | "generating" | "success" | "failed" | "failed_permanently";
  attempt: number;
  triggered_by: "schedule" | "manual";
  file_url: string | null;
  format: string | null;
  delivery_log: { recipient: string; type: RecipientType; status: string; error: string | null }[];
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface ReportTemplateInput {
  name: string;
  metrics: MetricKey[];
  date_range_type: DateRangeType;
  recurrence: Recurrence;
  recurrence_day?: number | null;
  recurrence_hour: number;
  recurrence_minute: number;
  timezone: string;
  recipients: Recipient[];
  format: ReportFormat;
  confirmed_external_send?: boolean;
}

// True whenever the confirmation modal (E-04) needs to appear before saving.
export function needsExternalRevenueConfirmation(metrics: MetricKey[], recipients: Recipient[]): boolean {
  return metrics.includes("revenue") && recipients.some((r) => r.type === "external");
}

export const CONFIRMATION_REQUIRED_ERROR = "confirmation_required";

export function listTemplates() {
  return api<{ templates: ReportTemplate[] }>("/reports/templates");
}

export async function createTemplate(data: ReportTemplateInput) {
  try {
    return await api<{ template: ReportTemplate }>("/reports/templates", {
      method: "POST",
      body: JSON.stringify(data),
    });
  } catch (err) {
    if (err instanceof ApiError && (err.body as { error?: string } | undefined)?.error === CONFIRMATION_REQUIRED_ERROR) {
      throw Object.assign(err, { needsConfirmation: true });
    }
    throw err;
  }
}

export async function updateTemplate(templateId: string, data: Partial<ReportTemplateInput>) {
  try {
    return await api<{ template: ReportTemplate; queued: boolean }>(`/reports/templates/${templateId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  } catch (err) {
    if (err instanceof ApiError && (err.body as { error?: string } | undefined)?.error === CONFIRMATION_REQUIRED_ERROR) {
      throw Object.assign(err, { needsConfirmation: true });
    }
    throw err;
  }
}

export function deleteTemplate(templateId: string) {
  return api<{ deleted: boolean }>(`/reports/templates/${templateId}`, { method: "DELETE" });
}

export function sendNow(templateId: string) {
  return api<{ run: ReportRun }>(`/reports/templates/${templateId}/send-now`, { method: "POST" });
}

export function listHistory(templateId?: string) {
  const query = templateId ? `?template_id=${encodeURIComponent(templateId)}` : "";
  return api<{ runs: ReportRun[] }>(`/reports/history${query}`);
}
