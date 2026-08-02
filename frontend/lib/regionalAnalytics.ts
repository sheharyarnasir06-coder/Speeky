import { api } from "./api";

// GAP-05 (US-203): Regional / Locale-Based Segmentation Analytics.

export const UNKNOWN_REGION = "UNKNOWN";
export const OTHER_REGIONS = "OTHER";

export type RegionalMetricKey = "daily_signups" | "day7_retention" | "revenue";

export const REGIONAL_METRIC_OPTIONS: { value: RegionalMetricKey; label: string }[] = [
  { value: "daily_signups", label: "Daily Signups" },
  { value: "day7_retention", label: "Day-7 Retention" },
  { value: "revenue", label: "Revenue" },
];

export interface RegionRollup {
  region_code: string;
  region_label: string;
  value: number;
  sample_size: number;
  is_low_volume: boolean;
  is_unknown: boolean;
  is_other_bucket: boolean;
  is_spoofing_flagged: boolean;
  spoofing_note: string | null;
}

export interface RegionalSegmentationResponse {
  metric_key: string;
  metric_label: string;
  date_from: string;
  date_to: string;
  min_sample_size: number;
  regions: RegionRollup[];
  computed_at: string | null;
  stale: boolean;
}

export interface RegionFeatureAdoptionRow {
  feature_label: string;
  started: number;
  completed: number;
  completion_rate: number;
}

export interface RegionDrilldownResponse {
  region_code: string;
  region_label: string;
  is_low_volume: boolean;
  sample_size: number;
  features: RegionFeatureAdoptionRow[];
  insufficient_data: boolean;
}

export function getRegionalSegmentation(metric: RegionalMetricKey, days = 30) {
  return api<RegionalSegmentationResponse>(`/analytics/regional/segments?metric=${metric}&days=${days}`);
}

export function getRegionDrilldown(regionCode: string, days = 30) {
  return api<RegionDrilldownResponse>(`/analytics/regional/${encodeURIComponent(regionCode)}?days=${days}`);
}
