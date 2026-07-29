"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { ShieldAlert, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import {
  deactivateThreshold,
  listThresholds,
  METRIC_OPTIONS,
  upsertThreshold,
  type AlertChannel,
  type MetricThreshold,
} from "@/lib/adminAlerts";

const THRESHOLD_TYPES = [
  { value: "stddev_multiplier", label: "Standard deviations from baseline" },
  { value: "percent_change", label: "Percent change from baseline" },
  { value: "absolute", label: "Absolute difference from baseline" },
];

const DIRECTIONS = [
  { value: "any", label: "Any direction" },
  { value: "above", label: "Increase only" },
  { value: "below", label: "Drop only" },
];

const CHANNELS: { value: AlertChannel; label: string }[] = [
  { value: "email", label: "Email" },
  { value: "slack", label: "Slack" },
  { value: "push", label: "Push (in-app)" },
];

export default function ThresholdsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [thresholds, setThresholds] = React.useState<MetricThreshold[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const [metricKey, setMetricKey] = React.useState(METRIC_OPTIONS[0].value);
  const [thresholdType, setThresholdType] = React.useState("stddev_multiplier");
  const [thresholdValue, setThresholdValue] = React.useState("2");
  const [direction, setDirection] = React.useState("any");
  const [channels, setChannels] = React.useState<AlertChannel[]>(["email"]);
  const [slackWebhookUrl, setSlackWebhookUrl] = React.useState("");

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  const refresh = React.useCallback(() => {
    listThresholds()
      .then((r) => setThresholds(r.thresholds))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load thresholds."));
  }, []);

  React.useEffect(() => {
    if (isAdmin) refresh();
  }, [isAdmin, refresh]);

  function toggleChannel(channel: AlertChannel) {
    setChannels((prev) => (prev.includes(channel) ? prev.filter((c) => c !== channel) : [...prev, channel]));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (channels.length === 0) {
      toast.error("Select at least one delivery channel.");
      return;
    }
    setSaving(true);
    try {
      await upsertThreshold({
        metric_key: metricKey,
        threshold_type: thresholdType as "stddev_multiplier" | "percent_change" | "absolute",
        threshold_value: parseFloat(thresholdValue),
        direction: direction as "above" | "below" | "any",
        channels,
        slack_webhook_url: channels.includes("slack") ? slackWebhookUrl || null : null,
      });
      toast.success("Threshold saved — you'll be notified when this metric breaches it.");
      refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't save threshold.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivate(id: string) {
    setBusyId(id);
    try {
      await deactivateThreshold(id);
      refresh();
      toast.success("Threshold turned off.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't deactivate threshold.");
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

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Threshold Settings
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Configure how sensitive each metric is, who owns it, and where the alert
          goes. A metric with no active threshold shows up in the Unassigned queue
          when it breaches.
        </p>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <Card elevation="raised">
        <CardHeader>
          <CardTitle className="text-lg">Add / update a threshold</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Select label="Metric" value={metricKey} onChange={(e) => setMetricKey(e.target.value as typeof metricKey)} options={METRIC_OPTIONS} />
            <Select label="Threshold type" value={thresholdType} onChange={(e) => setThresholdType(e.target.value)} options={THRESHOLD_TYPES} />
            <Input
              label={thresholdType === "percent_change" ? "Threshold value (%)" : "Threshold value"}
              type="number"
              step="0.1"
              min="0.1"
              value={thresholdValue}
              onChange={(e) => setThresholdValue(e.target.value)}
            />
            <Select label="Direction" value={direction} onChange={(e) => setDirection(e.target.value)} options={DIRECTIONS} />

            <div className="sm:col-span-2 flex flex-col gap-2">
              <span className="text-sm font-medium text-foreground">Delivery channels</span>
              <div className="flex flex-wrap gap-4">
                {CHANNELS.map((c) => (
                  <Checkbox key={c.value} label={c.label} checked={channels.includes(c.value)} onChange={() => toggleChannel(c.value)} />
                ))}
              </div>
            </div>

            {channels.includes("slack") ? (
              <div className="sm:col-span-2">
                <Input
                  label="Slack webhook URL"
                  hint="If this webhook is unreachable, delivery automatically falls back to email."
                  value={slackWebhookUrl}
                  onChange={(e) => setSlackWebhookUrl(e.target.value)}
                  placeholder="https://hooks.slack.com/services/..."
                />
              </div>
            ) : null}

            <div className="sm:col-span-2">
              <Button type="submit" loading={saving}>
                Save threshold
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface-elevated">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Metric</th>
              <th className="px-4 py-3">Sensitivity</th>
              <th className="px-4 py-3">Direction</th>
              <th className="px-4 py-3">Channels</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(thresholds ?? []).map((t) => (
              <tr key={t.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-medium text-foreground">
                  {METRIC_OPTIONS.find((m) => m.value === t.metric_key)?.label ?? t.metric_key}
                </td>
                <td className="px-4 py-3 text-muted-foreground">{t.threshold_value} ({t.threshold_type.replace("_", " ")})</td>
                <td className="px-4 py-3 text-muted-foreground">{t.direction}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    {t.channels.map((c) => (
                      <Badge key={c} tone="neutral">{c}</Badge>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-right">
                  <Button size="sm" variant="ghost" loading={busyId === t.id} onClick={() => handleDeactivate(t.id)}>
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                    Deactivate
                  </Button>
                </td>
              </tr>
            ))}
            {thresholds && thresholds.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  No thresholds configured yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
