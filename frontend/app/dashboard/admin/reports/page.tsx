"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Clock, FileText, Plus, Send, ShieldAlert, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import { METRIC_OPTIONS, type MetricKey } from "@/lib/adminAlerts";
import { listUsers } from "@/lib/adminUsers";
import {
  COMMON_TIMEZONES,
  DATE_RANGE_OPTIONS,
  RECURRENCE_OPTIONS,
  createTemplate,
  deleteTemplate,
  listTemplates,
  needsExternalRevenueConfirmation,
  sendNow,
  type DateRangeType,
  type Recurrence,
  type ReportFormat,
  type ReportTemplate,
  type ReportTemplateInput,
} from "@/lib/adminReports";

const WEEKDAYS = [
  { value: "0", label: "Monday" }, { value: "1", label: "Tuesday" }, { value: "2", label: "Wednesday" },
  { value: "3", label: "Thursday" }, { value: "4", label: "Friday" }, { value: "5", label: "Saturday" }, { value: "6", label: "Sunday" },
];
const FORMATS: { value: ReportFormat; label: string }[] = [
  { value: "pdf", label: "PDF" }, { value: "csv", label: "CSV" }, { value: "both", label: "Both" },
];

function recurrenceSummary(t: ReportTemplate): string {
  const time = `${String(t.recurrence_hour).padStart(2, "0")}:${String(t.recurrence_minute).padStart(2, "0")}`;
  if (t.recurrence === "none") return "Manual only";
  if (t.recurrence === "weekly") {
    const day = WEEKDAYS.find((w) => w.value === String(t.recurrence_day))?.label ?? "Monday";
    return `Weekly, ${day} ${time} (${t.timezone})`;
  }
  return `Monthly, day ${t.recurrence_day ?? 1} at ${time} (${t.timezone})`;
}

function emptyForm(): ReportTemplateInput {
  return {
    name: "", metrics: ["daily_signups"], date_range_type: "last_7_days", recurrence: "weekly",
    recurrence_day: 0, recurrence_hour: 9, recurrence_minute: 0, timezone: "UTC", recipients: [], format: "pdf",
  };
}

export default function ReportBuilderPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [templates, setTemplates] = React.useState<ReportTemplate[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);
  const [form, setForm] = React.useState<ReportTemplateInput>(emptyForm());
  const [saving, setSaving] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [admins, setAdmins] = React.useState<{ value: string; label: string }[]>([]);
  const [newRecipientType, setNewRecipientType] = React.useState<"internal" | "external">("internal");
  const [newRecipientValue, setNewRecipientValue] = React.useState("");

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  const refresh = React.useCallback(() => {
    listTemplates()
      .then((r) => setTemplates(r.templates))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load report templates."));
  }, []);

  React.useEffect(() => {
    if (isAdmin) refresh();
  }, [isAdmin, refresh]);

  React.useEffect(() => {
    if (isAdmin && admins.length === 0) {
      listUsers({ pageSize: 100 })
        .then((r) => setAdmins(r.users.map((u) => ({ value: u.id, label: `${u.name} (${u.email})` }))))
        .catch(() => {});
    }
  }, [isAdmin, admins.length]);

  function toggleMetric(key: MetricKey) {
    setForm((f) => ({
      ...f,
      metrics: f.metrics.includes(key) ? f.metrics.filter((m) => m !== key) : [...f.metrics, key],
    }));
  }

  function addRecipient() {
    if (!newRecipientValue.trim()) return;
    setForm((f) => ({ ...f, recipients: [...f.recipients, { type: newRecipientType, value: newRecipientValue.trim() }] }));
    setNewRecipientValue("");
  }

  function removeRecipient(index: number) {
    setForm((f) => ({ ...f, recipients: f.recipients.filter((_, i) => i !== index) }));
  }

  async function submitForm(confirmed: boolean) {
    if (!form.name.trim() || form.metrics.length === 0 || form.recipients.length === 0) {
      toast.error("Name, at least one metric, and at least one recipient are required.");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, confirmed_external_send: confirmed };
      await createTemplate(payload);
      toast.success("Report template created.");
      setShowForm(false);
      setForm(emptyForm());
      refresh();
    } catch (err) {
      const needsConfirmation = (err as { needsConfirmation?: boolean })?.needsConfirmation;
      if (needsConfirmation) {
        setConfirmOpen(true);
        return;
      }
      toast.error(err instanceof ApiError ? err.message : "Couldn't create report template.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSendNow(id: string) {
    setBusyId(id);
    try {
      await sendNow(id);
      toast.success("Report generation started.");
      refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't trigger report.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Delete this report template? This can't be undone.")) return;
    setBusyId(id);
    try {
      await deleteTemplate(id);
      toast.success("Report template deleted.");
      refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't delete report template.");
    } finally {
      setBusyId(null);
    }
  }

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Admin access required.</p>
      </div>
    );
  }

  const willNeedConfirmation = needsExternalRevenueConfirmation(form.metrics as MetricKey[], form.recipients);

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">Scheduled Reports</h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Recurring analytics packages, rendered from the same data the dashboard
            shows, emailed to whoever you configure.
          </p>
        </div>
        <div className="flex gap-2">
          <Button href="/dashboard/admin/reports/history" variant="outline" size="sm">
            <Clock className="h-4 w-4" aria-hidden="true" />
            History
          </Button>
          <Button size="sm" onClick={() => setShowForm((v) => !v)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            New report
          </Button>
        </div>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {showForm ? (
        <Card elevation="raised">
          <CardHeader>
            <CardTitle className="text-lg">New report template</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <Input label="Name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Weekly Growth Digest" />

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-foreground">Metrics</span>
              <div className="flex flex-wrap gap-4">
                {METRIC_OPTIONS.map((m) => (
                  <Checkbox key={m.value} label={m.label} checked={form.metrics.includes(m.value)} onChange={() => toggleMetric(m.value)} />
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Select label="Date range" value={form.date_range_type} onChange={(e) => setForm((f) => ({ ...f, date_range_type: e.target.value as DateRangeType }))} options={DATE_RANGE_OPTIONS} />
              <Select label="Format" value={form.format} onChange={(e) => setForm((f) => ({ ...f, format: e.target.value as ReportFormat }))} options={FORMATS} />
              <Select label="Recurrence" value={form.recurrence} onChange={(e) => setForm((f) => ({ ...f, recurrence: e.target.value as Recurrence }))} options={RECURRENCE_OPTIONS} />
            </div>

            {form.recurrence !== "none" ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
                {form.recurrence === "weekly" ? (
                  <Select
                    label="Day"
                    value={String(form.recurrence_day ?? 0)}
                    onChange={(e) => setForm((f) => ({ ...f, recurrence_day: Number(e.target.value) }))}
                    options={WEEKDAYS}
                  />
                ) : (
                  <Input
                    label="Day of month"
                    type="number"
                    min="1"
                    max="31"
                    value={String(form.recurrence_day ?? 1)}
                    onChange={(e) => setForm((f) => ({ ...f, recurrence_day: Number(e.target.value) }))}
                  />
                )}
                <Input
                  label="Hour (0-23)"
                  type="number"
                  min="0"
                  max="23"
                  value={String(form.recurrence_hour)}
                  onChange={(e) => setForm((f) => ({ ...f, recurrence_hour: Number(e.target.value) }))}
                />
                <Input
                  label="Minute"
                  type="number"
                  min="0"
                  max="59"
                  value={String(form.recurrence_minute)}
                  onChange={(e) => setForm((f) => ({ ...f, recurrence_minute: Number(e.target.value) }))}
                />
                <div>
                  <label className="text-sm font-medium text-foreground">Timezone</label>
                  <input
                    list="tz-options"
                    value={form.timezone}
                    onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
                    className="mt-1.5 h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
                  />
                  <datalist id="tz-options">
                    {COMMON_TIMEZONES.map((tz) => <option key={tz} value={tz} />)}
                  </datalist>
                  <p className="mt-1 text-xs text-muted-foreground">The schedule runs in this timezone, not server time.</p>
                </div>
              </div>
            ) : null}

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-foreground">Recipients</span>
              {willNeedConfirmation ? (
                <p className="text-xs text-warning">
                  Revenue is included and an external recipient is on this list — you&apos;ll be asked to confirm before saving.
                </p>
              ) : null}
              <div className="flex flex-col gap-2">
                {form.recipients.map((r, i) => (
                  <div key={`${r.type}-${r.value}-${i}`} className="flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                    <span className="flex items-center gap-2">
                      <Badge tone={r.type === "external" ? "warning" : "neutral"}>{r.type}</Badge>
                      {r.type === "internal" ? admins.find((a) => a.value === r.value)?.label ?? r.value : r.value}
                    </span>
                    <button type="button" onClick={() => removeRecipient(i)} aria-label="Remove recipient">
                      <X className="h-4 w-4 text-muted-foreground hover:text-danger" />
                    </button>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <div className="w-full sm:w-40">
                  <Select
                    label="Type"
                    hideLabel
                    value={newRecipientType}
                    onChange={(e) => setNewRecipientType(e.target.value as "internal" | "external")}
                    options={[{ value: "internal", label: "Internal admin" }, { value: "external", label: "External email" }]}
                  />
                </div>
                {newRecipientType === "internal" ? (
                  <div className="w-full flex-1">
                    <Select label="Admin" hideLabel value={newRecipientValue} onChange={(e) => setNewRecipientValue(e.target.value)} options={[{ value: "", label: "Select an admin..." }, ...admins]} />
                  </div>
                ) : (
                  <div className="flex-1">
                    <Input label="Email" value={newRecipientValue} onChange={(e) => setNewRecipientValue(e.target.value)} placeholder="stakeholder@company.com" />
                  </div>
                )}
                <Button type="button" variant="outline" onClick={addRecipient}>Add</Button>
              </div>
            </div>

            <div className="flex gap-2">
              <Button loading={saving} onClick={() => submitForm(false)}>Save report</Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Send Revenue data outside the organization?"
        description="This report includes Revenue and at least one external recipient. Confirm you intend to distribute financial data outside the org."
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button
            variant="danger"
            onClick={async () => {
              setConfirmOpen(false);
              await submitForm(true);
            }}
          >
            Confirm and save
          </Button>
        </div>
      </Modal>

      {templates && templates.length === 0 && !showForm ? (
        <EmptyState icon={<FileText className="h-6 w-6" aria-hidden="true" />} title="No report templates yet" description="Create one to start emailing recurring analytics packages." />
      ) : null}

      <div className="flex flex-col gap-4">
        {(templates ?? []).map((t) => (
          <Card key={t.id} elevation="raised" className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-foreground">{t.name}</span>
                {t.currently_generating ? <Badge tone="warning" dot>Generating…</Badge> : null}
                {t.pending_schedule_update ? <Badge tone="neutral">Edit queued — applies after current run</Badge> : null}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {t.metrics.map((m) => METRIC_OPTIONS.find((o) => o.value === m)?.label ?? m).join(", ")} · {recurrenceSummary(t)} ·{" "}
                {t.recipients.length} recipient{t.recipients.length === 1 ? "" : "s"}
              </p>
              {t.next_run_at ? (
                <p className="mt-1 text-xs text-muted-foreground">Next run: {new Date(t.next_run_at).toLocaleString()}</p>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button size="sm" variant="secondary" loading={busyId === t.id} onClick={() => handleSendNow(t.id)}>
                <Send className="h-4 w-4" aria-hidden="true" />
                Send now
              </Button>
              <Button size="sm" variant="ghost" loading={busyId === t.id} onClick={() => handleDelete(t.id)}>
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
