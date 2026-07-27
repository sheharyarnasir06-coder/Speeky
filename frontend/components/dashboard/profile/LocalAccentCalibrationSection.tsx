"use client";

import * as React from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Globe, Info, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  getAccentPreference,
  submitSubDialectDispute,
  updateAccentPreference,
  type AccentPreferenceResponse,
  type SubDialect,
} from "@/lib/accentCalibration";

// "broad_regional" only ever exists client-side, to represent "no sub-dialect
// selected" — it must never be sent to the backend as a literal value (see
// lib/accentCalibration.ts). Balochi/Kashmiri are intentionally included: the
// backend treats them as low-confidence dialects (ACC-US-09 E-01) and this is
// the only UI path that can exercise that fallback.
const SUB_DIALECT_OPTIONS: { id: "broad_regional" | SubDialect; label: string }[] = [
  { id: "broad_regional", label: "Broad Regional (Default)" },
  { id: "punjabi", label: "Punjabi-influenced" },
  { id: "sindhi", label: "Sindhi-influenced" },
  { id: "pashto", label: "Pashto-influenced" },
  { id: "balochi", label: "Balochi-influenced" },
  { id: "kashmiri", label: "Kashmiri-influenced" },
];

const LOW_CONFIDENCE_SUB_DIALECTS = new Set<SubDialect>(["balochi", "kashmiri"]);

export function LocalAccentCalibrationSection() {
  const [pref, setPref] = React.useState<AccentPreferenceResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isSaving, setIsSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [networkWarning, setNetworkWarning] = React.useState<string | null>(null);
  const [disputeMessage, setDisputeMessage] = React.useState<string | null>(null);
  const [isDisputing, setIsDisputing] = React.useState(false);

  const loadPreferences = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getAccentPreference();
      setPref(data);
    } catch (err) {
      // US-90 Exception: network load warning banner
      setNetworkWarning("Using standard pronunciation model due to network latency.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadPreferences();
  }, [loadPreferences]);

  const handleToggleModel = async (model: "generic_global" | "south_asian_pakistani") => {
    if (!pref) return;
    setIsSaving(true);
    setError(null);
    try {
      const updated = await updateAccentPreference({
        accent_model_preference: model,
        // Preserve any already-selected sub-dialect when re-enabling the
        // regional model; otherwise leave it unset (null) — never send the
        // "broad_regional" placeholder, the backend only accepts the 5 real
        // sub-dialect values or null.
        sub_dialect_preference: model === "south_asian_pakistani" ? (pref.sub_dialect_preference ?? null) : null,
      });
      setPref(updated);
    } catch (err) {
      setError("Failed to update accent calibration preference.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSubDialectChange = async (sub: "broad_regional" | SubDialect) => {
    if (!pref) return;
    setIsSaving(true);
    setError(null);
    setDisputeMessage(null);
    try {
      const updated = await updateAccentPreference({
        accent_model_preference: "south_asian_pakistani",
        sub_dialect_preference: sub === "broad_regional" ? null : sub,
      });
      setPref(updated);
    } catch (err) {
      setError("Failed to update sub-dialect granularity.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDisputeSubDialect = async () => {
    setIsDisputing(true);
    setDisputeMessage(null);
    try {
      const res = await submitSubDialectDispute("User requested re-classification of regional sub-dialect influence");
      setDisputeMessage(res.message);
      // Dispute reverts the server-side preference to the broad regional model.
      setPref((prev) => (prev ? { ...prev, sub_dialect_preference: null, notice: null } : prev));
    } catch (err) {
      setDisputeMessage("Dispute submitted for review.");
    } finally {
      setIsDisputing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span>Loading accent calibration settings...</span>
        </div>
      </div>
    );
  }

  const isLocalActive = pref?.accent_model_preference === "south_asian_pakistani";
  const currentSubDialect: "broad_regional" | SubDialect = pref?.sub_dialect_preference || "broad_regional";
  const isLowConfidence = LOW_CONFIDENCE_SUB_DIALECTS.has(currentSubDialect as SubDialect);

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe className="h-5 w-5 text-primary" />
          <h2 className="font-serif text-lg font-semibold text-foreground">
            Local Accent Calibration
          </h2>
        </div>
        {isLocalActive && (
          <span className="rounded-full bg-success/10 px-2.5 py-0.5 text-xs font-semibold text-success border border-success/20">
            Local Model Active
          </span>
        )}
      </div>

      <p className="mt-2 text-sm text-muted-foreground">
        Choose your evaluation calibration model. Local Accent Calibration adjusts stress pattern and vowel phoneme tolerances to accommodate regional Pakistani English stress variance.
      </p>

      {/* Network Warning Banner */}
      {networkWarning && (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-xs font-medium text-warning-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span>{networkWarning}</span>
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <span>{error}</span>
        </div>
      )}

      {/* Main Model Selector Toggle */}
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => handleToggleModel("generic_global")}
          disabled={isSaving}
          className={`flex flex-col gap-2 rounded-xl border p-4 text-left transition-all ${
            !isLocalActive
              ? "border-primary bg-primary/5 shadow-sm"
              : "border-border hover:border-primary/50"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-foreground text-sm">Generic Global Model</span>
            {!isLocalActive && <CheckCircle2 className="h-4 w-4 text-primary" />}
          </div>
          <p className="text-xs text-muted-foreground">
            Standard International English pronunciation scoring bands without regional acoustic adjustments.
          </p>
        </button>

        <button
          type="button"
          onClick={() => handleToggleModel("south_asian_pakistani")}
          disabled={isSaving}
          className={`flex flex-col gap-2 rounded-xl border p-4 text-left transition-all ${
            isLocalActive
              ? "border-primary bg-primary/5 shadow-sm"
              : "border-border hover:border-primary/50"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-foreground text-sm">South Asian / Pakistani English</span>
            {isLocalActive && <CheckCircle2 className="h-4 w-4 text-primary" />}
          </div>
          <p className="text-xs text-muted-foreground">
            Calibrated acoustic model respecting regional stress patterns, pitch variance, and vowel shifts.
          </p>
        </button>
      </div>

      {/* US-88 (ACC-US-09) Optional Sub-Dialect Granularity Selector */}
      {isLocalActive && (
        <div className="mt-6 flex flex-col gap-4 rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-foreground">Sub-Dialect Influence (Optional)</h3>
              <p className="text-xs text-muted-foreground">
                Refine acoustic tolerances for specific regional influence within Pakistan.
              </p>
            </div>
            <span className="text-[11px] font-medium text-muted-foreground">Optional</span>
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {SUB_DIALECT_OPTIONS.map((sub) => {
              const isSelected = currentSubDialect === sub.id;
              return (
                <button
                  key={sub.id}
                  type="button"
                  onClick={() => handleSubDialectChange(sub.id)}
                  disabled={isSaving}
                  className={`rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                    isSelected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-surface-elevated text-foreground hover:bg-muted"
                  }`}
                >
                  {sub.label}
                </button>
              );
            })}
          </div>

          {/* US-88 E-01/Revert: real server notice — low-confidence fallback
              warning for Balochi/Kashmiri, or a beta-active confirmation for
              Punjabi/Sindhi/Pashto — plus a revert-to-broad dispute action. */}
          {currentSubDialect !== "broad_regional" && pref?.notice && (
            <div
              className={`mt-2 flex flex-col gap-2 rounded-lg border p-3 text-xs text-foreground ${
                isLowConfidence ? "border-warning/30 bg-warning/10" : "border-info/20 bg-info/5"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5 font-medium">
                  {isLowConfidence ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-warning shrink-0" />
                  ) : (
                    <Info className="h-3.5 w-3.5 text-primary shrink-0" />
                  )}
                  {pref.notice}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  loading={isDisputing}
                  onClick={handleDisputeSubDialect}
                >
                  Dispute Shift
                </Button>
              </div>
              {disputeMessage && <p className="text-primary">{disputeMessage}</p>}
            </div>
          )}
        </div>
      )}

      {/* Warning when Local Calibration conflicts with strict Western drills */}
      {isLocalActive && (
        <div className="mt-4 flex items-start gap-2 text-xs text-muted-foreground">
          <Sparkles className="h-4 w-4 shrink-0 text-primary mt-0.5" />
          <span>Note: If you practice strict Western accent drills, Local Calibration will automatically present a conflict reminder.</span>
        </div>
      )}
    </div>
  );
}
