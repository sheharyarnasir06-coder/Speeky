"use client";

import * as React from "react";
import { HeartHandshake } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api";
import { getAccessibilityProfile, updateAccessibilityProfile } from "@/lib/pronunciationCoach";

/**
 * US-76: Accessibility safeguard for genuine speech disorders. Opt-in only —
 * never surfaced as a diagnosis, just a scoring-mode preference (see
 * lib/pronunciation_coach/accessibility_profile.py). When on, disclosed
 * disfluency (repetitions) is exempted from the fluency penalty; per-word
 * phoneme accuracy is always scored normally either way.
 */
export function AccessibilityProfileSection() {
  const [optedIn, setOptedIn] = React.useState<boolean | null>(null);
  const [condition, setCondition] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    getAccessibilityProfile()
      .then((data) => {
        setOptedIn(data.opted_in);
        setCondition(data.disclosed_condition ?? "");
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load this setting."));
  }, []);

  async function handleToggle(next: boolean) {
    setSaving(true);
    setError(null);
    try {
      const result = await updateAccessibilityProfile({
        opted_in: next,
        disclosed_condition: next ? condition || null : null,
      });
      setOptedIn(result.opted_in);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update this setting.");
    } finally {
      setSaving(false);
    }
  }

  if (optedIn === null) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
            <HeartHandshake className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-foreground">Accessibility-Aware Scoring</h2>
            <p className="text-sm text-muted-foreground">
              If speech practice feels more comfortable at your own pace, this excludes
              natural repetition from your fluency score. It never changes how individual
              words are scored for accuracy.
            </p>
          </div>
        </div>
        <Switch
          checked={optedIn}
          onCheckedChange={handleToggle}
          disabled={saving}
          label="Enable accessibility-aware scoring"
          hideLabel
        />
      </div>

      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

      {optedIn ? (
        <div className="mt-4">
          <label className="text-xs font-medium text-muted-foreground" htmlFor="disclosed-condition">
            Condition (optional, never shown to anyone else)
          </label>
          <input
            id="disclosed-condition"
            type="text"
            value={condition}
            onChange={(event) => setCondition(event.target.value)}
            onBlur={() => handleToggle(true)}
            placeholder="e.g. stutter"
            className="mt-1 h-10 w-full max-w-xs rounded-xl border border-input bg-surface px-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
        </div>
      ) : null}
    </div>
  );
}
