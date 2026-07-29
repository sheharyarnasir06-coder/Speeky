"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "react-toastify";
import { ShieldCheck, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import {
  CONSENT_CATEGORIES,
  CURRENT_CONSENT_VERSION,
  getConsentStatus,
  hasQueuedConsent,
  queueConsentForSync,
  saveConsent,
  syncQueuedConsent,
} from "@/lib/consent";

interface ConsentGateProps {
  children: React.ReactNode;
}

/** PRIV-US-02: required consent gate before learners can use the dashboard. */
export function ConsentGate({ children }: ConsentGateProps) {
  const { user, setUser, logout } = useAuth();
  const router = useRouter();
  const [checking, setChecking] = React.useState(true);
  const [required, setRequired] = React.useState(false);
  const [isSaving, setIsSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    async function loadConsent() {
      if (!user) return;

      if (
        user.isConsented &&
        user.consentVersion === CURRENT_CONSENT_VERSION &&
        Boolean(user.consentAcceptedAt) &&
        !hasQueuedConsent()
      ) {
        setRequired(false);
        setChecking(false);
        return;
      }

      try {
        const queued = await syncQueuedConsent().catch(() => null);
        const status = queued ?? (await getConsentStatus());
        if (cancelled) return;

        setRequired(!status.is_consented);
        setUser({
          ...user,
          isConsented: status.is_consented,
          consentVersion: status.consent_version,
          consentAcceptedAt: status.consent_accepted_at,
        });
      } catch {
        if (!cancelled) setRequired(true);
      } finally {
        if (!cancelled) setChecking(false);
      }
    }

    void loadConsent();

    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  React.useEffect(() => {
    async function handleOnline() {
      if (!user || !hasQueuedConsent()) return;

      try {
        const status = await syncQueuedConsent();
        if (!status) return;

        setRequired(!status.is_consented);
        setUser({
          ...user,
          isConsented: status.is_consented,
          consentVersion: status.consent_version,
          consentAcceptedAt: status.consent_accepted_at,
        });
        toast.success("Privacy consent synced.");
      } catch {
        // Keep queued; next online event or dashboard load retries.
      }
    }

    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [user, setUser]);

  async function handleAccept() {
    if (!user) return;

    setError(null);
    setIsSaving(true);
    try {
      const result = await saveConsent();
      setUser({
        ...user,
        isConsented: result.consent.is_consented,
        consentVersion: result.consent.consent_version,
        consentAcceptedAt: result.consent.consent_accepted_at,
      });
      setRequired(!result.consent.is_consented);
      toast.success("Consent saved.");
    } catch (err) {
      if (typeof navigator !== "undefined" && !navigator.onLine) {
        queueConsentForSync();
        setUser({ ...user, isConsented: true });
        setRequired(false);
        toast.info("Consent saved locally and will sync when you're online.");
        return;
      }

      const message =
        err instanceof ApiError && err.status === 409
          ? "The privacy policy changed. Please review this latest version and agree again."
          : err instanceof ApiError
            ? err.message
            : "Could not save consent. Please try again.";
      setError(message);
      toast.error(message);
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDecline() {
    await logout();
    toast.info("Consent is required to use Speeky.");
    router.push("/login");
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <span
          className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent text-muted-foreground"
          aria-hidden="true"
        />
      </div>
    );
  }

  return (
    <>
      {children}
      <Modal
        open={required}
        onClose={() => {}}
        title="Review Speeky's privacy consent"
        description="To use Speeky, you need to agree to the required data-use terms for this MVP."
        hideCloseButton
      >
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3 rounded-xl border border-border bg-surface px-4 py-3">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-medium text-foreground">
                Required consent for app access
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Speeky uses data for analytics, AI improvement, and product communication.
                If you decline, you&apos;ll be signed out.
              </p>
            </div>
          </div>

          <div className="flex flex-col divide-y divide-border rounded-xl border border-border">
            {CONSENT_CATEGORIES.map((category) => (
              <div key={category.id} className="px-4 py-3">
                <p className="text-sm font-medium text-foreground">{category.label}</p>
                <p className="text-xs text-muted-foreground">{category.description}</p>
              </div>
            ))}
          </div>

          {error ? (
            <div className="flex items-start gap-2 rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {error}
            </div>
          ) : null}

          <div className="flex flex-col gap-2 sm:flex-row">
            <Button type="button" loading={isSaving} onClick={handleAccept}>
              I Agree
            </Button>
            <Button type="button" variant="outline" disabled={isSaving} onClick={handleDecline}>
              Decline &amp; Sign Out
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
