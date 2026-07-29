"use client";

import * as React from "react";
import { AlertCircle, CheckCircle2, Clock, Download, ShieldAlert, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { useAuth } from "@/contexts/AuthContext";
import { API_ORIGIN, ApiError } from "@/lib/api";
import { listHistory, listTemplates, type ReportRun, type ReportTemplate } from "@/lib/adminReports";

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  success: "success",
  generating: "warning",
  pending: "neutral",
  failed: "danger",
  failed_permanently: "danger",
};

const STATUS_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  success: CheckCircle2,
  generating: Clock,
  pending: Clock,
  failed: XCircle,
  failed_permanently: XCircle,
};

const RECIPIENT_STATUS_TONE: Record<string, "success" | "danger" | "neutral"> = {
  sent: "success",
  bounced: "danger",
  failed: "danger",
};

export default function ReportHistoryPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [runs, setRuns] = React.useState<ReportRun[] | null>(null);
  const [templates, setTemplates] = React.useState<Record<string, ReportTemplate>>({});
  const [error, setError] = React.useState<string | null>(null);

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  React.useEffect(() => {
    if (!isAdmin) return;
    Promise.all([listHistory(), listTemplates()])
      .then(([historyRes, templatesRes]) => {
        setRuns(historyRes.runs);
        setTemplates(Object.fromEntries(templatesRes.templates.map((t) => [t.id, t])));
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load report history."));
  }, [isAdmin]);

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Admin access required.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">Report History</h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Every generation attempt — scheduled or manual — with per-recipient delivery status.
        </p>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {runs && runs.length === 0 ? (
        <EmptyState icon={<Clock className="h-6 w-6" aria-hidden="true" />} title="No reports sent yet" description="Once a scheduled or manual report runs, it'll show up here." />
      ) : null}

      <div className="flex flex-col gap-4">
        {(runs ?? []).map((run) => {
          const StatusIcon = STATUS_ICON[run.status] ?? Clock;
          const template = templates[run.template_id];
          const failures = run.delivery_log.filter((d) => d.status !== "sent");
          return (
            <Card key={run.id} elevation="raised" className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <StatusIcon className={`h-4 w-4 ${run.status === "success" ? "text-success" : run.status.startsWith("failed") ? "text-danger" : "text-warning"}`} aria-hidden="true" />
                  <span className="font-medium text-foreground">{template?.name ?? run.template_id}</span>
                  <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>{run.status.replace("_", " ")}</Badge>
                  <Badge tone="neutral">{run.triggered_by}</Badge>
                </div>
                <span className="text-xs text-muted-foreground">{new Date(run.started_at).toLocaleString()}</span>
              </div>

              {run.status === "failed_permanently" ? (
                <p className="mt-2 flex items-center gap-1.5 text-sm text-danger">
                  <AlertCircle className="h-4 w-4" aria-hidden="true" />
                  Generation failed after {run.attempt} attempt{run.attempt === 1 ? "" : "s"} — owner notified to view the dashboard directly.
                </p>
              ) : null}

              {run.file_url ? (
                <a
                  href={`${API_ORIGIN}${run.file_url}`}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  Download {run.format?.toUpperCase()}
                </a>
              ) : null}

              {run.delivery_log.length > 0 ? (
                <div className="mt-3 overflow-hidden rounded-lg border border-border">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-surface text-muted-foreground">
                      <tr>
                        <th className="px-3 py-1.5">Recipient</th>
                        <th className="px-3 py-1.5">Status</th>
                        <th className="px-3 py-1.5">Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.delivery_log.map((d, i) => (
                        <tr key={`${d.recipient}-${i}`} className="border-t border-border">
                          <td className="px-3 py-1.5 text-foreground">{d.recipient}</td>
                          <td className="px-3 py-1.5">
                            <Badge tone={RECIPIENT_STATUS_TONE[d.status] ?? "neutral"}>{d.status}</Badge>
                          </td>
                          <td className="px-3 py-1.5 text-muted-foreground">{d.error ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {failures.length > 0 ? (
                <p className="mt-2 text-xs text-warning">
                  {failures.length} of {run.delivery_log.length} recipient(s) failed — delivery still completed for the rest.
                </p>
              ) : null}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
