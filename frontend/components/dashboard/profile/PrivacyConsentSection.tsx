"use client";

import * as React from "react";
import { ShieldCheck } from "lucide-react";
import { toast } from "react-toastify";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import {
  CONSENT_CATEGORIES,
  CURRENT_CONSENT_VERSION,
  getConsentStatus,
  type ConsentStatus,
} from "@/lib/consent";
import { ApiError } from "@/lib/api";

/** PRIV-US-02: required consent status stored on the user record. */
export function PrivacyConsentSection() {
  const { user } = useAuth();
  const [status, setStatus] = React.useState<ConsentStatus | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const loadConsent = React.useCallback(async () => {
    if (!user) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await getConsentStatus();
      setStatus(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.status === 401
            ? "Your session expired. Please sign in again to view privacy consent."
            : err.message
          : "Could not load consent status.";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  React.useEffect(() => {
    void loadConsent();
  }, [loadConsent]);

  if (!user) return null;

  const isConsented = status?.is_consented ?? Boolean(user.isConsented);
  const acceptedAt = status?.consent_accepted_at ?? user.consentAcceptedAt ?? null;
  const policyVersion = status?.consent_version ?? user.consentVersion ?? CURRENT_CONSENT_VERSION;

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-foreground">Privacy &amp; Consent</h2>
          <p className="text-sm text-muted-foreground">
            Speeky requires consent for analytics, AI improvement, and product communication.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Status: {isConsented ? "Accepted" : "Not accepted"} - Policy: {policyVersion}
          </p>
          {acceptedAt ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Accepted on {new Date(acceptedAt).toLocaleString()}
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          loading={isLoading}
          onClick={() => {
            void loadConsent().then(() => toast.info("Consent status refreshed."));
          }}
        >
          Refresh
        </Button>
      </div>

      <div className="mt-4 flex flex-col divide-y divide-border border-t border-border">
        <div className="flex items-center justify-between gap-4 py-3">
          <div>
            <p className="text-sm font-medium text-foreground">Essential Account Data</p>
            <p className="text-xs text-muted-foreground">
              Required to operate your account - can&apos;t be turned off.
            </p>
          </div>
          <Switch checked disabled onCheckedChange={() => {}} label="Essential Account Data" hideLabel />
        </div>

        {CONSENT_CATEGORIES.map((category) => (
          <div
            key={category.id}
            className="flex items-center justify-between gap-4 py-3"
          >
            <div>
              <p className="text-sm font-medium text-foreground">{category.label}</p>
              <p className="text-xs text-muted-foreground">{category.description}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Required for Speeky access in this MVP.
              </p>
            </div>
            <Switch
              checked={isConsented}
              disabled
              onCheckedChange={() => {}}
              label={category.label}
              hideLabel
            />
          </div>
        ))}
      </div>

      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
    </div>
  );
}
