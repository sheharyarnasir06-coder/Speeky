"use client";

import * as React from "react";
import { toast } from "react-toastify";
import {
  AlertTriangle,
  BarChart3,
  Crown,
  Download,
  Filter,
  ShieldAlert,
  Trash2,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ApiError } from "@/lib/api";
import {
  CROSS_FILTER_FEATURES,
  exportAuditLoggedData,
  exportFeatureUsageCsv,
  exportFunnelCsv,
  exportRetentionByFeatureCsv,
  getFeatureUsage,
  getFunnel,
  getOverview,
  getRetentionByFeature,
  getRevenue,
  type CrossFilterFeature,
  type CrossFilterResult,
  type DashboardWidgetConfig,
  type FeatureUsageResult,
  type FunnelResult,
  type OverviewResult,
  type RevenueResult,
  type SavedViewResponse,
} from "@/lib/analytics";
import { useAuth } from "@/contexts/AuthContext";
import { SavedViewsBar } from "@/components/analytics/SavedViewsBar";
import { ReconciliationBadge } from "@/components/analytics/ReconciliationBadge";

const DAY_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "180", label: "Last 180 days" },
  { value: "365", label: "Last 365 days" },
];

type Tab = "overview" | "funnel" | "usage" | "cross-filter" | "revenue";

const HIGH_DROP_OFF_THRESHOLD = 50;

function Bar({ pct, tone = "brand" }: { pct: number; tone?: "brand" | "muted" }) {
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full", tone === "brand" ? "bg-primary" : "bg-muted-foreground/50")}
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}

function SplitBar({ totalPct, innerPct, title }: { totalPct: number; innerPct: number; title: string }) {
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted" title={title}>
      <div className="relative h-full rounded-full bg-primary/35" style={{ width: `${Math.max(0, Math.min(100, totalPct))}%` }}>
        <div className="absolute inset-y-0 left-0 rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, innerPct))}%` }} />
      </div>
    </div>
  );
}

function StatTile({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-2 font-serif text-3xl font-semibold text-foreground">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors",
        active ? "bg-primary text-primary-foreground" : "bg-surface text-muted-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

const DEFAULT_WIDGETS: DashboardWidgetConfig[] = [
  { id: "active_users_overview", position: 0 },
  { id: "daily_sessions", position: 1 },
  { id: "retention_funnel", position: 2 },
  { id: "feature_usage", position: 3 },
];

export default function AdminAnalyticsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [tab, setTab] = React.useState<Tab>("overview");
  const [days, setDays] = React.useState(30);

  // US-206 Saved view state
  const [activeView, setActiveView] = React.useState<SavedViewResponse | null>(null);
  const [activeWidgets, setActiveWidgets] = React.useState<Array<Record<string, unknown>>>(
    DEFAULT_WIDGETS.map((w) => ({ ...w }))
  );

  const role = user?.role ?? "";
  const isAdmin = role === "ADMIN" || role === "SUPER_ADMIN" || role === "COMPLIANCE" || role === "FINANCE";
  const isSuperAdmin = role === "SUPER_ADMIN";

  function handleApplyView(view: SavedViewResponse | null) {
    setActiveView(view);
    if (view) {
      if (view.filters?.days && typeof view.filters.days === "number") {
        setDays(view.filters.days);
      } else {
        setDays(30);
      }
      
      if (view.filters?.tab && typeof view.filters.tab === "string") {
        const targetTab = view.filters.tab as Tab;
        if (targetTab === "revenue" && !isSuperAdmin) {
          setTab("overview");
        } else {
          setTab(targetTab);
        }
      } else {
        setTab("overview");
      }
      
      setActiveWidgets(view.widgets || []);
      toast.info(`Loaded view "${view.name}"`);
    } else {
      setDays(30);
      setTab("overview");
      setActiveWidgets(DEFAULT_WIDGETS.map((w) => ({ ...w })));
    }
  }

  function handleRemoveWidget(widgetId: string) {
    setActiveWidgets((prev) => prev.filter((w) => w.id !== widgetId));
    toast.success(`Removed widget from current layout.`);
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

  return (
    <div className="flex flex-col gap-8">
      {/* Header with Title + Date Range + Reconciliation Badge */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
            Analytics & Operations
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Platform activity, onboarding drop-off, feature adoption, and payment reconciliation.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 sm:justify-end">
          <ReconciliationBadge />
          <div className="w-full sm:w-48">
            <Select label="Date range" hideLabel value={String(days)} onChange={(e) => setDays(Number(e.target.value))} options={DAY_OPTIONS} />
          </div>
        </div>
      </div>

      {/* US-206 Saved Views Bar */}
      <SavedViewsBar
        currentFilters={{ days, tab }}
        currentWidgets={activeWidgets as unknown as DashboardWidgetConfig[]}
        activeView={activeView}
        onApplyView={handleApplyView}
        onRemoveDeprecatedWidget={handleRemoveWidget}
      />

      {/* Deprecated widget placeholders if present in active view */}
      {activeWidgets.some((w) => w.deprecated || w.placeholder_label) ? (
        <div className="flex flex-col gap-3">
          {activeWidgets
            .filter((w) => w.deprecated || w.placeholder_label)
            .map((w, idx) => (
              <div
                key={String(w.id || idx)}
                className="flex items-center justify-between rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm text-foreground shadow-sm"
              >
                <div className="flex items-center gap-3">
                  <AlertTriangle className="h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
                  <div>
                    <p className="font-semibold text-xs uppercase tracking-wide text-warning">Deprecated Widget</p>
                    <p className="text-xs">
                      Widget <code className="font-mono">{String(w.id)}</code> is no longer available: {String(w.placeholder_label || "This widget is no longer available")}
                    </p>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveWidget(String(w.id))}
                  className="h-8 text-xs text-danger hover:bg-danger/10"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  Remove from View
                </Button>
              </div>
            ))}
        </div>
      ) : null}

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        <TabButton active={tab === "overview"} onClick={() => setTab("overview")}>Overview</TabButton>
        <TabButton active={tab === "funnel"} onClick={() => setTab("funnel")}>Onboarding Funnel</TabButton>
        <TabButton active={tab === "usage"} onClick={() => setTab("usage")}>Feature Usage</TabButton>
        <TabButton active={tab === "cross-filter"} onClick={() => setTab("cross-filter")}>Retention Cross-Filter</TabButton>
        {isSuperAdmin ? (
          <TabButton active={tab === "revenue"} onClick={() => setTab("revenue")}>
            <span className="inline-flex items-center gap-1">
              <Crown className="h-3.5 w-3.5" aria-hidden="true" />
              Revenue & Reconciliation
            </span>
          </TabButton>
        ) : null}
      </div>

      {tab === "overview" ? <OverviewTab days={days} /> : null}
      {tab === "funnel" ? <FunnelTab days={days} /> : null}
      {tab === "usage" ? <FeatureUsageTab days={days} /> : null}
      {tab === "cross-filter" ? <CrossFilterTab days={days} /> : null}
      {tab === "revenue" && isSuperAdmin ? <RevenueTab days={days} /> : null}
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────────
function OverviewTab({ days }: { days: number }) {
  const [data, setData] = React.useState<OverviewResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    setData(null);
    setError(null);
    getOverview(days)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load analytics."));
  }, [days]);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  if (data.zero_data) {
    return (
      <EmptyState
        icon={<BarChart3 className="h-7 w-7" aria-hidden="true" />}
        title="Not enough data collected for this period yet"
        description="Try a wider date range once more learners have practiced."
      />
    );
  }

  const maxDaily = Math.max(1, ...data.daily_sessions.map((d) => d.count));

  return (
    <div className="flex flex-col gap-8">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile label="Active users" value={data.active_users} hint={`Trailing ${data.period_days} days`} />
        <StatTile
          label="7-day retention"
          value={data.retention_rate === null ? "TBD" : `${data.retention_rate}%`}
          hint={data.retention_rate === null ? "No cohort old enough yet" : "Signed up 7+ days ago, still active"}
        />
        <StatTile label="Practice sessions" value={data.daily_sessions.reduce((sum, d) => sum + d.count, 0)} hint="Across every module" />
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <h3 className="font-serif text-lg font-semibold text-foreground">Daily sessions</h3>
        <div className="mt-4 flex h-32 items-end gap-1">
          {data.daily_sessions.map((d) => (
            <div
              key={d.date}
              title={`${d.date}: ${d.count} session${d.count === 1 ? "" : "s"}`}
              className="flex-1 rounded-t bg-primary transition-all"
              style={{ height: `${Math.max(2, (d.count / maxDaily) * 100)}%` }}
            />
          ))}
        </div>
      </div>

      <div>
        <h3 className="font-serif text-lg font-semibold text-foreground">Onboarding funnel</h3>
        <MiniFunnel funnel={data.onboarding_funnel} />
      </div>

      <div>
        <h3 className="font-serif text-lg font-semibold text-foreground">Top features</h3>
        <div className="mt-3 flex flex-col gap-2">
          {data.top_feature_usage.map((f) => (
            <div key={f.key} className="flex items-center gap-3 text-sm">
              <span className="w-40 shrink-0 truncate text-foreground">{f.label}</span>
              <Bar pct={(f.started / Math.max(1, data.top_feature_usage[0].started)) * 100} />
              <span className="w-10 shrink-0 text-right text-muted-foreground">{f.started}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function MiniFunnel({ funnel }: { funnel: OverviewResult["onboarding_funnel"] }) {
  return (
    <div className="mt-3 flex flex-col gap-3">
      {funnel.map((step) => (
        <div key={step.step} className="flex items-center gap-3 text-sm">
          <span className="w-44 shrink-0 truncate text-foreground">{step.step}</span>
          <Bar pct={step.pct_of_start} />
          <span className="w-32 shrink-0 text-right text-muted-foreground">
            {step.count} ({step.pct_of_start}%)
          </span>
          {step.drop_off_pct > HIGH_DROP_OFF_THRESHOLD ? (
            <Badge tone="danger" className="shrink-0">
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
              {step.drop_off_pct}% drop-off
            </Badge>
          ) : null}
        </div>
      ))}
    </div>
  );
}

// ── Funnel (Audit Logged Export) ─────────────────────────────────────────────
function FunnelTab({ days }: { days: number }) {
  const [data, setData] = React.useState<FunnelResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => {
    setData(null);
    setError(null);
    getFunnel(days)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the funnel."));
  }, [days]);

  async function handleExport() {
    setExporting(true);
    try {
      await exportFunnelCsv(days);
      toast.success("Funnel CSV exported and recorded in audit log.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Audit-logged export failed.");
    } finally {
      setExporting(false);
    }
  }

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Funnel starts at Registration — the first step measured in this application.
        </p>
        <Button size="sm" variant="outline" loading={exporting} onClick={handleExport}>
          <Download className="h-4 w-4" aria-hidden="true" />
          Export CSV (Audit-Logged)
        </Button>
      </div>

      {data.zero_data ? (
        <EmptyState
          icon={<TrendingDown className="h-7 w-7" aria-hidden="true" />}
          title="No traffic recorded for this period"
          description="No one registered in this window yet."
        />
      ) : (
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <MiniFunnel funnel={data.funnel} />
        </div>
      )}
    </div>
  );
}

// ── Feature Usage (Audit Logged Export) ──────────────────────────────────────
function FeatureUsageTab({ days }: { days: number }) {
  const [data, setData] = React.useState<FeatureUsageResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showArchived, setShowArchived] = React.useState(false);
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => {
    setData(null);
    setError(null);
    getFeatureUsage(days, showArchived)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load feature usage."));
  }, [days, showArchived]);

  async function handleExport() {
    setExporting(true);
    try {
      await exportFeatureUsageCsv(days, showArchived);
      toast.success("Feature usage CSV exported and recorded in audit log.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Audit-logged export failed.");
    } finally {
      setExporting(false);
    }
  }

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const maxStarted = Math.max(1, ...data.features.map((f) => f.started));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          Show archived scenarios
        </label>
        <Button size="sm" variant="outline" loading={exporting} onClick={handleExport}>
          <Download className="h-4 w-4" aria-hidden="true" />
          Export CSV (Audit-Logged)
        </Button>
      </div>

      {data.zero_data ? (
        <EmptyState
          icon={<BarChart3 className="h-7 w-7" aria-hidden="true" />}
          title="Not enough data collected for this period yet"
          description="No scenario sessions were started in this window."
        />
      ) : (
        <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          {data.features.map((f) => (
            <div key={f.key} className="flex items-center gap-3 text-sm">
              <span className="flex w-48 shrink-0 items-center gap-1.5 truncate text-foreground">
                {f.label}
                {f.new ? <Badge tone="brand" size="sm">New</Badge> : null}
                {f.archived ? <Badge tone="neutral" size="sm">Archived</Badge> : null}
              </span>
              <div className="flex-1">
                <SplitBar
                  totalPct={(f.started / maxStarted) * 100}
                  innerPct={(f.started / maxStarted) * (f.completion_rate / 100) * 100}
                  title={`${f.started} started, ${f.completed} completed (${f.completion_rate}%)`}
                />
              </div>
              <span className="w-36 shrink-0 text-right text-muted-foreground">
                {f.started} started · {f.completion_rate}% done
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Cross-Filter (Audit Logged Export) ───────────────────────────────────────
function CrossFilterTab({ days }: { days: number }) {
  const [feature, setFeature] = React.useState<CrossFilterFeature>("scenario_based_learning");
  const [data, setData] = React.useState<CrossFilterResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => {
    setData(null);
    setError(null);
    getRetentionByFeature(days, feature)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load this comparison."));
  }, [days, feature]);

  async function handleExport() {
    setExporting(true);
    try {
      await exportRetentionByFeatureCsv(days, feature);
      toast.success("Retention comparison exported and recorded in audit log.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Audit-logged export failed.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-full max-w-xs">
          <Select
            label="Feature"
            value={feature}
            onChange={(e) => setFeature(e.target.value as CrossFilterFeature)}
            options={CROSS_FILTER_FEATURES}
          />
        </div>
        <Button size="sm" variant="outline" loading={exporting} onClick={handleExport} disabled={!data || data.zero_data}>
          <Download className="h-4 w-4" aria-hidden="true" />
          Export CSV (Audit-Logged)
        </Button>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {!error && !data ? <p className="text-sm text-muted-foreground">Loading…</p> : null}

      {data?.status === "processing" ? (
        <div className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
          <Filter className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          {data.message}
        </div>
      ) : null}

      {data && data.status !== "processing" && data.zero_data ? (
        <EmptyState
          icon={<Users className="h-7 w-7" aria-hidden="true" />}
          title="No users match this filter criteria"
          description="No one signed up in this window yet for this comparison."
        />
      ) : null}

      {data && data.status !== "processing" && !data.zero_data && data.engaged && data.general ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-2xl border border-primary/30 bg-primary/5 p-5 shadow-sm">
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-primary">
              <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
              Used {data.feature_label} in first 7 days
            </p>
            <p className="mt-2 font-serif text-3xl font-semibold text-foreground">
              {data.engaged.retention_rate === null ? "TBD" : `${data.engaged.retention_rate}%`}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{data.engaged.cohort_size}-user cohort · 7-day retention</p>
          </div>
          <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">General users</p>
            <p className="mt-2 font-serif text-3xl font-semibold text-foreground">
              {data.general.retention_rate === null ? "TBD" : `${data.general.retention_rate}%`}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{data.general.cohort_size}-user cohort · 7-day retention</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── Revenue (Audit Logged Export + US-207 Reconciliation) ────────────────────
function RevenueTab({ days }: { days: number }) {
  const [data, setData] = React.useState<RevenueResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => {
    setData(null);
    setError(null);
    getRevenue(days)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load revenue data."));
  }, [days]);

  async function handleExportRevenue() {
    setExporting(true);
    try {
      await exportAuditLoggedData("Revenue", { days }, "csv", "revenue_export.csv");
      toast.success("Revenue data exported and logged in audit trail.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Audit-logged revenue export failed.");
    } finally {
      setExporting(false);
    }
  }

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const maxMrr = Math.max(1, ...data.mrr_series.map((m) => m.mrr));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-4 py-2.5 text-sm text-foreground">
          <Crown className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          {data.note}
        </div>
        <Button size="sm" variant="outline" loading={exporting} onClick={handleExportRevenue}>
          <Download className="h-4 w-4" aria-hidden="true" />
          Export Revenue CSV (Audit-Logged)
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <StatTile label="Current MRR" value={`$${data.current_mrr.toLocaleString()}`} hint={data.currency} />
        <StatTile label="Churn rate" value={`${data.churn_rate_pct}%`} hint="Monthly" />
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <h3 className="font-serif text-lg font-semibold text-foreground">MRR trend</h3>
        <div className="mt-4 flex h-32 items-end gap-1">
          {data.mrr_series.map((m) => (
            <div
              key={m.date}
              title={`${m.date}: $${m.mrr.toLocaleString()}`}
              className="flex-1 rounded-t bg-primary"
              style={{ height: `${Math.max(2, (m.mrr / maxMrr) * 100)}%` }}
            />
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface-elevated">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Cohort</th>
              <th className="px-4 py-3">Day 1</th>
              <th className="px-4 py-3">Day 7</th>
              <th className="px-4 py-3">Day 30</th>
            </tr>
          </thead>
          <tbody>
            {data.cohort_retention.map((row) => (
              <tr key={row.cohort} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-medium text-foreground">{row.cohort}</td>
                <td className="px-4 py-3 text-muted-foreground">{row.day1}%</td>
                <td className="px-4 py-3 text-muted-foreground">{row.day7}%</td>
                <td className="px-4 py-3 text-muted-foreground">
                  {row.day30 === null ? <span className="text-muted-foreground/60">TBD</span> : `${row.day30}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
