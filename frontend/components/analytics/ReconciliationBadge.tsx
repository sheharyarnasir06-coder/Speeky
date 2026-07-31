"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ReconciliationModal } from "./ReconciliationModal";
import { getReconciliationStatus, type ReconciliationSummaryResponse } from "@/lib/analytics";

interface ReconciliationBadgeProps {
  initialData?: ReconciliationSummaryResponse | null;
}

export function ReconciliationBadge({ initialData }: ReconciliationBadgeProps) {
  const [statusData, setStatusData] = React.useState<ReconciliationSummaryResponse | null>(
    initialData || null
  );
  const [loading, setLoading] = React.useState(!initialData);
  const [isModalOpen, setIsModalOpen] = React.useState(false);

  const fetchStatus = React.useCallback(async () => {
    setLoading(true);
    try {
      const data = await getReconciliationStatus();
      setStatusData(data);
    } catch {
      // Optional toast
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  if (loading && !statusData) {
    return <span className="text-xs text-muted-foreground">Checking reconciliation…</span>;
  }

  const status = statusData?.status || "RECONCILIATION_PENDING";

  return (
    <>
      <button
        type="button"
        onClick={() => setIsModalOpen(true)}
        className="group transition-transform hover:scale-105 focus:outline-none"
        title="Click to open cross-source reconciliation details"
      >
        {status === "RECONCILED" ? (
          <Badge tone="success" className="gap-1.5 cursor-pointer py-1 px-3">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            Reconciled
          </Badge>
        ) : status === "DISCREPANCY_DETECTED" ? (
          <Badge tone="danger" className="gap-1.5 cursor-pointer py-1 px-3 animate-pulse">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            Data Discrepancy Detected
          </Badge>
        ) : status === "RECONCILIATION_FAILED" ? (
          <Badge tone="danger" className="gap-1.5 cursor-pointer py-1 px-3">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            Reconciliation Failed
          </Badge>
        ) : (
          <Badge tone="warning" className="gap-1.5 cursor-pointer py-1 px-3">
            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
            Reconciliation Pending
          </Badge>
        )}
      </button>

      <ReconciliationModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        statusData={statusData}
        onRefreshStatus={fetchStatus}
      />
    </>
  );
}
