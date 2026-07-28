"use client";

import * as React from "react";
import { BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import {
  getNotificationPreferences,
  updateNotificationPreferences,
  type NotificationCadence,
} from "@/lib/notifications";

const CADENCE_OPTIONS: { id: NotificationCadence; label: string; description: string }[] = [
  {
    id: "remind_if_not_practiced",
    label: "Remind me if I haven't practiced",
    description: "One nudge per day, only if you haven't practiced yet.",
  },
  {
    id: "always",
    label: "Always notify",
    description: "Streak reminders and milestone celebrations, as they happen.",
  },
  {
    id: "off",
    label: "Off entirely",
    description: "No proactive nudges. You can still earn streaks and badges.",
  },
];

/** Notification Frequency Controls & Quiet Hours (US-169 / GAP-08). */
export function NotificationPreferencesSection() {
  const { user } = useAuth();
  const [quietStart, setQuietStart] = React.useState("22:00");
  const [quietEnd, setQuietEnd] = React.useState("08:00");
  const [cadence, setCadence] = React.useState<NotificationCadence>("remind_if_not_practiced");
  const [loaded, setLoaded] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [justSaved, setJustSaved] = React.useState(false);

  React.useEffect(() => {
    if (!user) return;
    getNotificationPreferences()
      .then((prefs) => {
        setQuietStart(prefs.quiet_hours_start);
        setQuietEnd(prefs.quiet_hours_end);
        setCadence(prefs.cadence);
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [user]);

  if (!user || !loaded) return null;

  async function handleSave() {
    setSaving(true);
    try {
      await updateNotificationPreferences({
        quiet_hours_start: quietStart,
        quiet_hours_end: quietEnd,
        cadence,
      });
      setJustSaved(true);
      window.setTimeout(() => setJustSaved(false), 3000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <BellRing className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Notifications</h2>
          <p className="text-sm text-muted-foreground">
            Control when streak reminders and milestone celebrations reach you. Quiet
            hours apply to every gamification notification, not just reminders.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-4 border-t border-border pt-4">
        <div>
          <p className="text-sm font-medium text-foreground">Quiet hours</p>
          <p className="text-xs text-muted-foreground">
            No push notifications during this window, even overnight.
          </p>
          {/* A native time input carries a fixed intrinsic width, so two of them plus
              the separator overflowed a 375px viewport by 23px. min-w-0 lets the flex
              items shrink below that intrinsic size, and the row wraps as a last
              resort on the narrowest phones. */}
          <div className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-2">
            <label className="flex min-w-0 flex-1 basis-28 flex-col gap-1 text-xs text-muted-foreground">
              From
              <input
                type="time"
                value={quietStart}
                onChange={(e) => setQuietStart(e.target.value)}
                className="w-full min-w-0 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-foreground"
              />
            </label>
            <span className="pb-2 text-muted-foreground" aria-hidden="true">–</span>
            <label className="flex min-w-0 flex-1 basis-28 flex-col gap-1 text-xs text-muted-foreground">
              To
              <input
                type="time"
                value={quietEnd}
                onChange={(e) => setQuietEnd(e.target.value)}
                className="w-full min-w-0 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-foreground"
              />
            </label>
          </div>
        </div>

        <div>
          <p className="text-sm font-medium text-foreground">Reminder cadence</p>
          <div className="mt-2 grid grid-cols-1 gap-2">
            {CADENCE_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setCadence(option.id)}
                className={cn(
                  "rounded-xl border p-3 text-left transition-colors",
                  cadence === option.id
                    ? "border-primary bg-secondary"
                    : "border-border hover:bg-surface",
                )}
              >
                <p className="text-sm font-semibold text-foreground">{option.label}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{option.description}</p>
              </button>
            ))}
          </div>
        </div>
      </div>

      {justSaved ? (
        <p className="mt-4 text-sm text-success">Notification preferences updated.</p>
      ) : null}

      <Button type="button" size="sm" className="mt-4" loading={saving} onClick={handleSave}>
        Save Preferences
      </Button>
    </div>
  );
}
