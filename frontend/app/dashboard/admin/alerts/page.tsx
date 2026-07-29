"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { AlertTriangle, CheckCircle2, Layers, ShieldAlert, Sliders, UserPlus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import {
  acknowledgeAlert,
  assignUnassignedAlert,
  listAlerts,
  listUnassignedAlerts,
  markFalsePositive,
  METRIC_OPTIONS,
  type AnomalyAlert,
} from "@/lib/adminAlerts";
import { listUsers } from "@/lib/adminUsers";

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "false_positive", label: "False positive" },
  { value: "resolved", label: "Resolved" },
];

const STATUS_TONE: Record<string, "danger" | "warning" | "neutral" | "success"> = {
  open: "danger",
  acknowledged: "warning",
  false_positive: "neutral",
  resolved: "success",
};

function groupByDigest(alerts: AnomalyAlert[]): AnomalyAlert[][] {
  const groups = new Map<string, AnomalyAlert[]>();
  const solo: AnomalyAlert[][] = [];
  for (const alert of alerts) {
    if (alert.digest_group_id) {
      const list = groups.get(alert.digest_group_id) ?? [];
      list.push(alert);
      groups.set(alert.digest_group_id, list);
    } else {
      solo.push([alert]);
    }
  }
  return [...groups.values(), ...solo].sort(
    (a, b) => new Date(b[0].created_at).getTime() - new Date(a[0].created_at).getTime(),
  );
}

function AlertRow({ alert, onAck, onFalsePositive, busy }: {
  alert: AnomalyAlert;
  onAck: (id: string) => void;
  onFalsePositive: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-border p-4 first:border-t-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-foreground">{alert.metric_label}</span>
          <Badge tone={STATUS_TONE[alert.status] ?? "neutral"}>{alert.status.replace("_", " ")}</Badge>
          {alert.is_unassigned ? <Badge tone="warning">Unassigned</Badge> : null}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          value {alert.value} vs baseline {alert.baseline_value.toFixed(2)} ({alert.deviation.toFixed(2)} deviation) —{" "}
          {new Date(alert.created_at).toLocaleString()}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button size="sm" variant="outline" href={alert.deep_link_path}>
          View on dashboard
        </Button>
        {alert.status === "open" ? (
          <>
            <Button size="sm" variant="secondary" loading={busy} onClick={() => onAck(alert.id)}>
              Acknowledge
            </Button>
            <Button size="sm" variant="ghost" loading={busy} onClick={() => onFalsePositive(alert.id)}>
              False positive
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}

export default function AdminAlertsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [tab, setTab] = React.useState<"alerts" | "unassigned">("alerts");
  const [alerts, setAlerts] = React.useState<AnomalyAlert[] | null>(null);
  const [unassigned, setUnassigned] = React.useState<AnomalyAlert[] | null>(null);
  const [admins, setAdmins] = React.useState<{ value: string; label: string }[]>([]);
  const [assignPick, setAssignPick] = React.useState<Record<string, string>>({});
  const [status, setStatus] = React.useState("");
  const [metric, setMetric] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";
  const isSuperAdmin = user?.role === "SUPER_ADMIN";

  const refreshAlerts = React.useCallback(() => {
    listAlerts({ status: status || undefined, metric_key: metric || undefined })
      .then((r) => setAlerts(r.alerts))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load alerts."));
  }, [status, metric]);

  const refreshUnassigned = React.useCallback(() => {
    listUnassignedAlerts()
      .then((r) => setUnassigned(r.alerts))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load unassigned alerts."));
  }, []);

  React.useEffect(() => {
    if (isAdmin) refreshAlerts();
  }, [isAdmin, refreshAlerts]);

  React.useEffect(() => {
    if (isSuperAdmin && tab === "unassigned") {
      refreshUnassigned();
      if (admins.length === 0) {
        listUsers({ role: "ADMIN", pageSize: 100 })
          .then((r) => setAdmins(r.users.map((u) => ({ value: u.id, label: `${u.name} (${u.email})` }))))
          .catch(() => {});
      }
    }
  }, [isSuperAdmin, tab, refreshUnassigned, admins.length]);

  async function handleAck(id: string) {
    setBusyId(id);
    try {
      await acknowledgeAlert(id);
      refreshAlerts();
      toast.success("Alert acknowledged.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't acknowledge alert.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleFalsePositive(id: string) {
    setBusyId(id);
    try {
      await markFalsePositive(id);
      refreshAlerts();
      toast.success("Marked as false positive.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't mark as false positive.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleAssign(id: string) {
    const ownerId = assignPick[id] ?? user?.id;
    if (!ownerId) return;
    setBusyId(id);
    try {
      await assignUnassignedAlert(id, ownerId);
      refreshUnassigned();
      toast.success("Owner assigned.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't assign owner.");
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

  const groups = alerts ? groupByDigest(alerts) : [];

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
            Alert Center
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Anomalies detected against each metric&apos;s rolling baseline. Metrics that
            breached together are grouped into one digest.
          </p>
        </div>
        <Button href="/dashboard/admin/alerts/thresholds" variant="outline" size="sm">
          <Sliders className="h-4 w-4" aria-hidden="true" />
          Threshold settings
        </Button>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {isSuperAdmin ? (
        <div className="flex gap-2 border-b border-border">
          <button
            type="button"
            onClick={() => setTab("alerts")}
            className={`px-3 py-2 text-sm font-medium ${tab === "alerts" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground"}`}
          >
            All Alerts
          </button>
          <button
            type="button"
            onClick={() => setTab("unassigned")}
            className={`px-3 py-2 text-sm font-medium ${tab === "unassigned" ? "border-b-2 border-primary text-foreground" : "text-muted-foreground"}`}
          >
            Unassigned Queue {unassigned && unassigned.length > 0 ? `(${unassigned.length})` : ""}
          </button>
        </div>
      ) : null}

      {tab === "alerts" ? (
        <>
          <div className="flex flex-col gap-4 sm:flex-row">
            <div className="w-full sm:w-56">
              <Select label="Status" hideLabel value={status} onChange={(e) => setStatus(e.target.value)} options={STATUS_FILTERS} />
            </div>
            <div className="w-full sm:w-56">
              <Select
                label="Metric"
                hideLabel
                value={metric}
                onChange={(e) => setMetric(e.target.value)}
                options={[{ value: "", label: "All metrics" }, ...METRIC_OPTIONS]}
              />
            </div>
          </div>

          {alerts && groups.length === 0 ? (
            <EmptyState
              icon={<CheckCircle2 className="h-6 w-6" aria-hidden="true" />}
              title="No alerts"
              description="Nothing has breached its baseline for this filter."
            />
          ) : null}

          <div className="flex flex-col gap-4">
            {groups.map((group) => (
              <Card key={group[0].digest_group_id ?? group[0].id} elevation="raised">
                {group.length > 1 ? (
                  <div className="flex items-center gap-2 border-b border-border bg-danger/5 px-4 py-2 text-sm font-medium text-danger">
                    <Layers className="h-4 w-4" aria-hidden="true" />
                    {group.length} metrics affected around the same time — possible shared cause
                  </div>
                ) : null}
                {group.map((alert) => (
                  <AlertRow key={alert.id} alert={alert} onAck={handleAck} onFalsePositive={handleFalsePositive} busy={busyId === alert.id} />
                ))}
              </Card>
            ))}
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-4">
          {unassigned && unassigned.length === 0 ? (
            <EmptyState
              icon={<CheckCircle2 className="h-6 w-6" aria-hidden="true" />}
              title="Nothing unassigned"
              description="Every breaching metric currently has a configured owner."
            />
          ) : null}
          {(unassigned ?? []).map((alert) => (
            <Card key={alert.id} elevation="raised" className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
                  <span className="font-medium text-foreground">{alert.metric_label}</span>
                  <span className="text-sm text-muted-foreground">— no owner configured</span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  value {alert.value} vs baseline {alert.baseline_value.toFixed(2)} — {new Date(alert.created_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-56">
                  <Select
                    label="Assign to"
                    hideLabel
                    value={assignPick[alert.id] ?? user?.id ?? ""}
                    onChange={(e) => setAssignPick((prev) => ({ ...prev, [alert.id]: e.target.value }))}
                    options={admins.length ? admins : [{ value: user?.id ?? "", label: "Myself" }]}
                  />
                </div>
                <Button size="sm" loading={busyId === alert.id} onClick={() => handleAssign(alert.id)}>
                  <UserPlus className="h-4 w-4" aria-hidden="true" />
                  Assign
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
