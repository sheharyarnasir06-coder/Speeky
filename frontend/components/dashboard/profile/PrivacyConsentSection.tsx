"use client";

import * as React from "react";
import { ShieldCheck } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/AuthContext";
import {
  CONSENT_CATEGORIES,
  getConsentPreferences,
  setConsent,
  type ConsentPreferences,
} from "@/lib/consent";

/** US-06 : Privacy & Consent controls. */
export function PrivacyConsentSection() {
  const { user } = useAuth();
  const [preferences, setPreferences] =
    React.useState<ConsentPreferences | null>(null);

  React.useEffect(() => {
    if (!user) return;

    setPreferences(getConsentPreferences(user.id));
  }, [user]);

  if (!user || !preferences) return null;

  function handleToggle(
    category: (typeof CONSENT_CATEGORIES)[number]["id"],
    granted: boolean,
  ) {
    const result = setConsent(user!.id, category, granted);
    setPreferences(result.preferences);
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            Privacy &amp; Consent
          </h2>
          <p className="text-sm text-muted-foreground">
            Manage how your data is used. Changes are recorded to a viewable
            history below.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-col divide-y divide-border border-t border-border">
        <div className="flex items-center justify-between py-3">
          <div>
            <p className="text-sm font-medium text-foreground">
              Essential Account Data
            </p>
            <p className="text-xs text-muted-foreground">
              Required to operate your account — can&apos;t be turned off.
            </p>
          </div>
          <Switch
            checked
            disabled
            onCheckedChange={() => {}}
            label="Essential Account Data"
            hideLabel
          />
        </div>

        {CONSENT_CATEGORIES.map((category) => (
          <div
            key={category.id}
            className="flex items-center justify-between py-3"
          >
            <div>
              <p className="text-sm font-medium text-foreground">
                {category.label}
              </p>
              <p className="text-xs text-muted-foreground">
                {category.description}
              </p>
            </div>
            <Switch
              checked={preferences[category.id]}
              onCheckedChange={(checked) => handleToggle(category.id, checked)}
              label={category.label}
              hideLabel
            />
          </div>
        ))}
      </div>
    </div>
  );
}
