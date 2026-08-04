"use client";

import * as React from "react";
import { toast } from "react-toastify";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  runReconciliationJob,
  resyncUserRecord,
  type ReconciliationSummaryResponse,
  type ReconciliationProviderResult,
  type MismatchedItem,
} from "@/lib/analytics";
import { ApiError } from "@/lib/api";

interface ReconciliationModalProps {
  isOpen: boolean;
  onClose: () => void;
  statusData: ReconciliationSummaryResponse | null;
  onRefreshStatus: () => Promise<void>;
}

export function ReconciliationModal({
  isOpen,
  onClose,
  statusData,
  onRefreshStatus,
}: ReconciliationModalProps) {
  const [running, setRunning] = React.useState(false);
  const [resyncingUserId, setResyncingUserId] = React.useState<string | null>(null);

  // Single record resync target
  const [targetItem, setTargetItem] = React.useState<{
    user_id: string;
    provider: string;
    transaction_id: string;
  } | null>(null);
  const [resyncReason, setResyncReason] = React.useState("unsynced_refund_or_chargeback");

  async function handleRunReconciliation() {
    setRunning(true);
    try {
      const updated = await runReconciliationJob();
      if (updated.status === "RECONCILED") {
        toast.success("Reconciliation completed: All sources reconciled within tolerance.");
      } else if (updated.status === "DISCREPANCY_DETECTED") {
        toast.error("Reconciliation completed: Discrepancy detected!");
      } else if (updated.status === "RECONCILIATION_FAILED") {
        toast.error("Reconciliation failed: Provider APIs exhausted retry limit.");
      } else {
        toast.warning("Reconciliation pending: Provider API retrying.");
      }
      await onRefreshStatus();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to run reconciliation job.");
    } finally {
      setRunning(false);
    }
  }

  async function handleConfirmResync() {
    if (!targetItem) return;
    setResyncingUserId(targetItem.user_id);
    try {
      await resyncUserRecord({
        user_id: targetItem.user_id,
        transaction_id: targetItem.transaction_id || `txn_${targetItem.user_id}`,
        provider: targetItem.provider,
        reason: resyncReason,
      });
      // Close the confirmation modal first, then refresh so the discrepancy
      // row disappears from the table and the variance figures update.
      setTargetItem(null);
      await onRefreshStatus();
      toast.success(
        `Re-sync actioned for ${targetItem.user_id} — discrepancy removed from ${targetItem.provider} table.`
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Targeted re-sync failed.");
    } finally {
      setResyncingUserId(null);
    }
  }

  if (!isOpen) return null;

  const providersList = statusData ? Object.values(statusData.providers) : [];

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Cross-Source Data Reconciliation (US-207)"
    >
      <div className="flex flex-col gap-6 max-w-3xl">
        {/* Header & Run Trigger */}
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-surface-elevated p-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">Overall Status:</span>
              {statusData?.status === "RECONCILED" ? (
                <Badge tone="success" className="gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  Reconciled
                </Badge>
              ) : statusData?.status === "DISCREPANCY_DETECTED" ? (
                <Badge tone="danger" className="gap-1">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                  Data Discrepancy Detected
                </Badge>
              ) : statusData?.status === "RECONCILIATION_FAILED" ? (
                <Badge tone="danger" className="gap-1">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                  Reconciliation Failed
                </Badge>
              ) : (
                <Badge tone="warning" className="gap-1">
                  <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                  Reconciliation Pending
                </Badge>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Tolerance: {statusData?.tolerance_pct ?? 1.0}% variance · Computed:{" "}
              {statusData?.computed_at ? new Date(statusData.computed_at).toLocaleString() : "Never"}
            </p>
          </div>

          <Button variant="primary" size="sm" loading={running} onClick={handleRunReconciliation}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Run Reconciliation Now
          </Button>
        </div>

        {/* Message / Retry details if pending */}
        {statusData?.status === "RECONCILIATION_FAILED" ? (
          <div className="flex items-center gap-3 rounded-xl border border-danger/30 bg-danger/10 p-3 text-xs text-foreground">
            <AlertTriangle className="h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
            <div>
              <p className="font-semibold text-danger">Reconciliation Failed — Provider APIs Unavailable</p>
              <p>{statusData?.message || "Maximum retry limit exceeded. Please check provider status."}</p>
            </div>
          </div>
        ) : statusData?.pending || statusData?.status === "RECONCILIATION_PENDING" ? (
          <div className="flex items-center gap-3 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-foreground">
            <Clock className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            <div>
              <p className="font-semibold">Provider API Unavailable — Retrying</p>
              <p>{statusData?.message || `Retry count ${statusData?.retry_count ?? 1}/3. Showing pending state.`}</p>
            </div>
          </div>
        ) : null}

        {/* Provider Comparisons */}
        <div className="flex flex-col gap-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Payment Provider Breakdown (Stripe, Apple, Google)
          </h4>

          {providersList.length === 0 ? (
            <p className="text-xs text-muted-foreground">No reconciliation runs recorded yet. Click &quot;Run Reconciliation Now&quot; above.</p>
          ) : (
            providersList.map((prov) => (
              <ProviderCard
                key={prov.provider}
                prov={prov}
                onResyncClick={(item) =>
                  setTargetItem({
                    user_id: item.user_id,
                    provider: prov.provider,
                    transaction_id: item.transaction_id || `txn_${item.user_id}`,
                  })
                }
              />
            ))
          )}
        </div>
      </div>

      {/* Target Re-sync Modal */}
      {targetItem ? (
        <Modal
          open={Boolean(targetItem)}
          onClose={() => setTargetItem(null)}
          title={`Targeted Re-sync — User ${targetItem.user_id}`}
        >
          <div className="flex flex-col gap-4 text-sm">
            <p className="text-xs text-muted-foreground">
              Queue a single-record re-sync with <strong className="capitalize text-foreground">{targetItem.provider}</strong> to correct unsynced refunds or chargebacks without reloading full system data.
            </p>

            <Input
              label="Transaction ID"
              value={targetItem.transaction_id}
              onChange={(e) => setTargetItem({ ...targetItem, transaction_id: e.target.value })}
            />

            <Input
              label="Re-sync Reason"
              value={resyncReason}
              onChange={(e) => setResyncReason(e.target.value)}
              placeholder="e.g. unsynced_refund_or_chargeback"
            />

            <div className="flex justify-end gap-3 pt-2">
              <Button variant="outline" onClick={() => setTargetItem(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={resyncingUserId === targetItem.user_id}
                onClick={handleConfirmResync}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                Trigger Re-sync
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </Modal>
  );
}

function ProviderCard({
  prov,
  onResyncClick,
}: {
  prov: ReconciliationProviderResult;
  onResyncClick: (item: MismatchedItem) => void;
}) {
  const isOk = prov.status === "RECONCILED";
  const isPending = prov.status === "RECONCILIATION_PENDING";
  const isFailed = prov.status === "RECONCILIATION_FAILED";

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface-elevated p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-serif text-base font-semibold capitalize text-foreground">{prov.provider} Gateway</span>
          {isOk ? (
            <Badge tone="success" size="sm">Reconciled</Badge>
          ) : isPending ? (
            <Badge tone="warning" size="sm">Pending</Badge>
          ) : isFailed ? (
            <Badge tone="danger" size="sm">Unavailable</Badge>
          ) : (
            <Badge tone="danger" size="sm">Discrepancy ({prov.variance_pct}% variance)</Badge>
          )}
        </div>
        {prov.grace_applied_count > 0 ? (
          <span className="text-xs text-muted-foreground">
            {prov.grace_applied_count} item(s) excluded via timing grace buffer
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 rounded-xl bg-surface p-3 text-xs sm:grid-cols-2">
        <div>
          <span className="text-muted-foreground">Internal Analytics:</span>{" "}
          <strong className="font-semibold text-foreground">${prov.internal_revenue.toLocaleString()}</strong> ({prov.internal_count} txns)
        </div>
        <div>
          <span className="text-muted-foreground">Provider Reported:</span>{" "}
          <strong className="font-semibold text-foreground">${prov.provider_revenue.toLocaleString()}</strong> ({prov.provider_count} txns)
        </div>
      </div>

      {prov.mismatched_items && prov.mismatched_items.length > 0 ? (
        <div className="flex flex-col gap-2 pt-1">
          <span className="text-xs font-semibold text-danger">Line-Item Discrepancies:</span>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-surface text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">User ID</th>
                  <th className="px-3 py-2">Variance Delta</th>
                  <th className="px-3 py-2">Renewal Time</th>
                  <th className="px-3 py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {prov.mismatched_items.map((item, idx) => (
                  <tr key={item.user_id || idx} className="hover:bg-muted/30">
                    <td className="px-3 py-2 font-mono font-medium text-foreground">{item.user_id}</td>
                    <td className="px-3 py-2 font-medium text-danger">${Math.abs(item.delta)}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {item.renewal_at ? new Date(item.renewal_at).toLocaleTimeString() : "N/A"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button variant="ghost" size="sm" className="h-6 text-[11px] gap-1" onClick={() => onResyncClick(item)}>
                        <RotateCcw className="h-3 w-3" aria-hidden="true" />
                        Targeted Re-sync
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
