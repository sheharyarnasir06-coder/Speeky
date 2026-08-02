"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { ChevronRight, Globe2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { ApiError } from "@/lib/api";
import {
  OTHER_REGIONS,
  REGIONAL_METRIC_OPTIONS,
  UNKNOWN_REGION,
  getRegionDrilldown,
  getRegionalSegmentation,
  type RegionalMetricKey,
  type RegionDrilldownResponse,
  type RegionRollup,
} from "@/lib/regionalAnalytics";
import { RegionConfidenceBadge } from "./RegionConfidenceBadge";

function isPercentMetric(metric: RegionalMetricKey): boolean {
  return metric === "day7_retention";
}

function formatValue(metric: RegionalMetricKey, value: number): string {
  if (isPercentMetric(metric)) return `${value}%`;
  if (metric === "revenue") return `$${value.toLocaleString()}`;
  return value.toLocaleString();
}

function RegionRow({ region, maxValue, metric, onDrilldown }: {
  region: RegionRollup;
  maxValue: number;
  metric: RegionalMetricKey;
  onDrilldown: (code: string) => void;
}) {
  const pct = maxValue > 0 ? Math.max(2, (region.value / maxValue) * 100) : 0;
  const canDrilldown = !region.is_other_bucket;

  return (
    <div className="flex items-center gap-3 py-2">
      <button
        type="button"
        disabled={!canDrilldown}
        onClick={() => canDrilldown && onDrilldown(region.region_code)}
        className="flex w-40 shrink-0 items-center gap-1.5 truncate text-left text-sm font-medium text-foreground disabled:cursor-default"
      >
        {region.region_label}
        {canDrilldown ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" /> : null}
      </button>
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-24 shrink-0 text-right text-sm text-muted-foreground">{formatValue(metric, region.value)}</span>
      <div className="flex w-40 shrink-0 flex-wrap justify-end gap-1">
        {region.is_unknown ? <Badge tone="neutral" title="Users with no country on file yet">Unknown Region</Badge> : null}
        {region.is_other_bucket ? <Badge tone="neutral" title="Regions below the minimum reporting threshold, combined">Other Regions</Badge> : null}
        {region.is_spoofing_flagged && region.spoofing_note ? <RegionConfidenceBadge note={region.spoofing_note} /> : null}
      </div>
    </div>
  );
}

export function RegionComparisonView() {
  const [metric, setMetric] = React.useState<RegionalMetricKey>("daily_signups");
  const [data, setData] = React.useState<Awaited<ReturnType<typeof getRegionalSegmentation>> | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [drilldownRegion, setDrilldownRegion] = React.useState<string | null>(null);
  const [drilldown, setDrilldown] = React.useState<RegionDrilldownResponse | null>(null);

  React.useEffect(() => {
    setData(null);
    setError(null);
    getRegionalSegmentation(metric)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load regional segmentation."));
  }, [metric]);

  function openDrilldown(regionCode: string) {
    setDrilldownRegion(regionCode);
    setDrilldown(null);
    getRegionDrilldown(regionCode)
      .then(setDrilldown)
      .catch((err) => toast.error(err instanceof ApiError ? err.message : "Couldn't load region detail."));
  }

  const maxValue = data ? Math.max(1, ...data.regions.map((r) => r.value)) : 1;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="w-full max-w-xs">
          <Select
            label="Metric"
            value={metric}
            onChange={(e) => setMetric(e.target.value as RegionalMetricKey)}
            options={REGIONAL_METRIC_OPTIONS}
          />
        </div>
        {data?.stale ? (
          <p className="text-xs text-muted-foreground">No rollup computed yet — the nightly job hasn&apos;t run.</p>
        ) : data?.computed_at ? (
          <p className="text-xs text-muted-foreground">Precomputed {new Date(data.computed_at).toLocaleString()}</p>
        ) : null}
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {!data && !error ? <Skeleton className="h-48 w-full rounded-2xl" /> : null}

      {data && data.regions.length === 0 ? (
        <EmptyState
          icon={<Globe2 className="h-6 w-6" aria-hidden="true" />}
          title="No regional data yet"
          description="Regional rollups are precomputed on a schedule — check back after the next run."
        />
      ) : null}

      {data && data.regions.length > 0 ? (
        <div className="rounded-2xl border border-border bg-surface-elevated px-4 py-2">
          {data.regions.map((region) => (
            <div key={region.region_code} className="border-b border-border last:border-0">
              <RegionRow region={region} maxValue={maxValue} metric={metric} onDrilldown={openDrilldown} />
            </div>
          ))}
        </div>
      ) : null}

      {drilldownRegion ? (
        <div className="rounded-2xl border border-border bg-surface p-4">
          <h4 className="font-serif text-base font-semibold text-foreground">
            {drilldownRegion === UNKNOWN_REGION ? "Unknown Region" : drilldownRegion === OTHER_REGIONS ? "Other Regions" : drilldownRegion} — feature adoption
          </h4>
          {!drilldown ? (
            <Skeleton className="mt-3 h-24 w-full rounded-xl" />
          ) : drilldown.insufficient_data ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Insufficient data for this region (below the minimum reporting threshold of {drilldown.sample_size} users) — feature-level breakdown is suppressed to avoid identifying individual users.
            </p>
          ) : (
            <div className="mt-3 flex flex-col gap-2">
              {drilldown.features.map((f) => (
                <div key={f.feature_label} className="flex items-center justify-between text-sm">
                  <span className="text-foreground">{f.feature_label}</span>
                  <span className="text-muted-foreground">{f.started} started · {f.completion_rate}% completed</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
