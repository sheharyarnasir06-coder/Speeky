"use client";

import * as React from "react";
import { toast } from "react-toastify";
import {
  AlertTriangle,
  CheckCircle2,
  Code,
  FileText,
  Filter,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { EmptyState } from "@/components/ui/empty-state";
import {
  getAuditLogs,
  verifyAuditLogIntegrity,
  type AuditLogEntry,
  type AuditLogListResponse,
} from "@/lib/analytics";
import { ApiError } from "@/lib/api";

const ACTION_TYPE_OPTIONS = [
  { value: "", label: "All Action Types" },
  { value: "EXPORT", label: "Export (Data Export)" },
  { value: "VIEW_RESTRICTED", label: "View Restricted" },
  { value: "FILTER", label: "Filter Change" },
];

export default function AuditLogsPage() {
  const { user, isLoading: authLoading } = useAuth();

  const [logsData, setLogsData] = React.useState<AuditLogListResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  // Filters
  const [actorId, setActorId] = React.useState("");
  const [actionType, setActionType] = React.useState("");
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");

  // Verification state
  const [verifying, setVerifying] = React.useState(false);
  const [verificationResult, setVerificationResult] = React.useState<{
    chain_intact: boolean;
    checked_at: string;
  } | null>(null);

  // Modal scope viewer
  const [selectedEntry, setSelectedEntry] = React.useState<AuditLogEntry | null>(null);

  const role = user?.role ?? "";
  const isAuthorized = role === "COMPLIANCE" || role === "SUPER_ADMIN";

  const fetchLogs = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAuditLogs({
        actor_id: actorId || undefined,
        action_type: actionType || undefined,
        date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
        date_to: dateTo ? new Date(dateTo).toISOString() : undefined,
      });
      setLogsData(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load audit logs.");
    } finally {
      setLoading(false);
    }
  }, [actorId, actionType, dateFrom, dateTo]);

  React.useEffect(() => {
    if (isAuthorized) {
      fetchLogs();
    }
  }, [isAuthorized, fetchLogs]);

  async function handleVerify() {
    setVerifying(true);
    try {
      const res = await verifyAuditLogIntegrity();
      setVerificationResult(res);
      if (res.chain_intact) {
        toast.success("Audit log integrity verified successfully!");
      } else {
        toast.error("WARNING: Audit log tampering detected!");
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Verification call failed.");
    } finally {
      setVerifying(false);
    }
  }

  if (authLoading) return null;

  if (!isAuthorized) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <h2 className="font-serif text-lg font-semibold text-foreground">Access Restricted</h2>
        <p className="text-sm text-muted-foreground">
          Audit Log Trail is restricted to Compliance Officers and Super Administrators only.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
            Admin Action Audit Trail
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Tamper-evident, hash-chained log of analytics access, export requests, and administrative actions.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={fetchLogs} loading={loading}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Refresh
          </Button>
          <Button variant="primary" size="sm" onClick={handleVerify} loading={verifying}>
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            Verify Integrity
          </Button>
        </div>
      </div>

      {/* Verification / Tamper Alerts */}
      {logsData?.tamper_detected || (verificationResult && !verificationResult.chain_intact) ? (
        <div className="flex items-center gap-3 rounded-2xl border border-danger bg-danger/10 p-4 text-danger">
          <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold text-sm">TAMPERING DETECTED IN AUDIT LOG</p>
            <p className="text-xs">
              One or more hash signatures fail to match the prev_hash chain sequence. Contact security immediately.
            </p>
          </div>
        </div>
      ) : null}

      {verificationResult?.chain_intact ? (
        <div className="flex items-center gap-3 rounded-2xl border border-success bg-success/10 p-4 text-foreground">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden="true" />
          <div className="text-xs">
            <span className="font-semibold text-success">Log Chain Verified Intact:</span> All stored entries match SHA-256 hash sequence as of{" "}
            {new Date(verificationResult.checked_at).toLocaleTimeString()}.
          </div>
        </div>
      ) : null}

      {/* Filter Toolbar */}
      <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <Filter className="h-3.5 w-3.5" aria-hidden="true" />
          Filter Audit Entries
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            label="Actor ID"
            placeholder="e.g. admin_001"
            value={actorId}
            onChange={(e) => setActorId(e.target.value)}
          />
          <Select
            label="Action Type"
            value={actionType}
            onChange={(e) => setActionType(e.target.value)}
            options={ACTION_TYPE_OPTIONS}
          />
          <Input
            label="Date From"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <Input
            label="Date To"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {/* Audit Log Table */}
      {error ? (
        <div className="rounded-2xl border border-danger/30 bg-danger/5 p-4 text-sm text-danger">
          {error}
        </div>
      ) : loading ? (
        <p className="text-sm text-muted-foreground">Loading audit log entries…</p>
      ) : !logsData || logsData.entries.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-7 w-7" aria-hidden="true" />}
          title="No audit entries found"
          description="No administrative actions match your current filter settings."
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Showing {logsData.entries.length} of {logsData.total} recorded events</span>
            <span className="font-mono">Tamper Status: {logsData.tamper_detected ? "CORRUPTED" : "CLEAN"}</span>
          </div>

          <div className="overflow-hidden rounded-2xl border border-border bg-surface-elevated shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border bg-surface text-xs uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Timestamp</th>
                    <th className="px-4 py-3">Actor</th>
                    <th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Module</th>
                    <th className="px-4 py-3">Export / Filter Scope</th>
                    <th className="px-4 py-3">SHA-256 Hash</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {logsData.entries.map((entry) => (
                    <tr key={entry.id} className="hover:bg-muted/30 transition-colors">
                      <td className="whitespace-nowrap px-4 py-3 text-xs font-mono text-muted-foreground">
                        {new Date(entry.timestamp).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col">
                          <span className="font-medium text-foreground text-xs font-mono">{entry.actor_id}</span>
                          <Badge tone={entry.actor_role === "SUPER_ADMIN" ? "brand" : "neutral"} className="w-fit mt-0.5 text-[10px]">
                            {entry.actor_role}
                          </Badge>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          tone={
                            entry.action_type === "EXPORT"
                              ? "warning"
                              : entry.action_type === "VIEW_RESTRICTED"
                              ? "danger"
                              : "neutral"
                          }
                        >
                          {entry.action_type}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-medium text-foreground text-xs">
                        {entry.module}
                      </td>
                      <td className="px-4 py-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setSelectedEntry(entry)}
                          className="h-7 text-xs gap-1.5"
                        >
                          <Code className="h-3.5 w-3.5" aria-hidden="true" />
                          View Scope
                        </Button>
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">
                        <span title={entry.entry_hash} className="truncate max-w-[120px] inline-block">
                          {entry.entry_hash.slice(0, 16)}…
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Scope Inspector Modal */}
      {selectedEntry ? (
        <Modal
          open={Boolean(selectedEntry)}
          onClose={() => setSelectedEntry(null)}
          title={`Scope Details — ${selectedEntry.action_type} (${selectedEntry.module})`}
        >
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
              <div>
                <span className="text-muted-foreground">Entry ID:</span>{" "}
                <span className="font-mono font-medium text-foreground">{selectedEntry.id}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Actor:</span>{" "}
                <span className="font-mono font-medium text-foreground">{selectedEntry.actor_id} ({selectedEntry.actor_role})</span>
              </div>
              <div>
                <span className="text-muted-foreground">Timestamp:</span>{" "}
                <span className="font-mono text-foreground">{new Date(selectedEntry.timestamp).toISOString()}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Prev Hash:</span>{" "}
                <span className="font-mono text-foreground">{selectedEntry.prev_hash.slice(0, 12)}…</span>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-foreground">Exact Scope JSON</label>
              <pre className="max-h-60 overflow-y-auto rounded-xl bg-surface border border-border p-3 text-xs font-mono text-foreground">
                {JSON.stringify(selectedEntry.scope, null, 2)}
              </pre>
            </div>

            <div className="flex justify-end pt-2">
              <Button variant="outline" size="sm" onClick={() => setSelectedEntry(null)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
