"use client";

import * as React from "react";
import { Globe2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  getTargetAccent,
  listTargetAccents,
  selectTargetAccent,
  type TargetAccentOption,
} from "@/lib/accentAssessment";

/**
 * US-82 (ACC-US-03): Target Accent / English Variant Selection. The accent
 * list is fetched from the backend's registry (not hardcoded here) — real
 * consequence: whichever accent is selected genuinely changes how
 * pronunciation is scored the next time real word-level phoneme data flows
 * through the shared pipeline (see pronunciation_pipeline.py's
 * AccentPronunciationConfigRegistry).
 */
export function TargetAccentSection() {
  const [options, setOptions] = React.useState<TargetAccentOption[] | null>(null);
  const [currentId, setCurrentId] = React.useState<string | null>(null);
  const [confirmation, setConfirmation] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState<string | null>(null);

  React.useEffect(() => {
    Promise.all([listTargetAccents(), getTargetAccent()])
      .then(([accents, pref]) => {
        setOptions(accents.accents);
        setCurrentId(pref.current_accent_id);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load target accents."));
  }, []);

  async function handleSelect(accentId: string) {
    setSaving(accentId);
    setError(null);
    setConfirmation(null);
    try {
      const result = await selectTargetAccent(accentId);
      setCurrentId(result.accent.id);
      setConfirmation(result.fallback_message ?? result.confirmation_message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update your target accent.");
    } finally {
      setSaving(null);
    }
  }

  if (!options) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <Globe2 className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Target Accent</h2>
          <p className="text-sm text-muted-foreground">
            Choose which English variant your pronunciation is scored against.
          </p>
        </div>
      </div>

      {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}
      {confirmation ? <p className="mt-4 text-sm text-success">{confirmation}</p> : null}

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {options.map((accent) => (
          <button
            key={accent.id}
            type="button"
            disabled={saving !== null}
            onClick={() => handleSelect(accent.id)}
            className={cn(
              "rounded-xl border p-4 text-left transition-colors disabled:opacity-60",
              currentId === accent.id
                ? "border-primary bg-secondary"
                : "border-border hover:bg-surface",
            )}
          >
            <p className="text-sm font-semibold text-foreground">{accent.label}</p>
            <p className="mt-1 text-xs text-muted-foreground">{accent.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
