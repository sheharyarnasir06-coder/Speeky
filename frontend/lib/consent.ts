import { ApiError, api } from "./api";
import { PRIVACY_VERSION } from "./privacy-content";

export type ConsentCategory = "analytics" | "ai_training" | "marketing";
export const CURRENT_CONSENT_VERSION = PRIVACY_VERSION;

export interface ConsentCategoryOption {
  id: ConsentCategory;
  label: string;
  description: string;
}

export const CONSENT_CATEGORIES: ConsentCategoryOption[] = [
  {
    id: "analytics",
    label: "Usage Analytics",
    description: "Speeky uses activity and usage patterns to improve reliability and product decisions.",
  },
  {
    id: "ai_training",
    label: "AI Training & Improvement",
    description: "Practice content and feedback signals may be used to improve Speeky's coaching quality.",
  },
  {
    id: "marketing",
    label: "Marketing Communications",
    description: "Speeky may use your account details to send product updates, tips, and announcements.",
  },
];

export interface ConsentStatus {
  is_consented: boolean;
  consent_version: string | null;
  consent_accepted_at: string | null;
}

export interface ConsentSaveResponse {
  consent: ConsentStatus;
}

const PENDING_CONSENT_KEY = "speeky:pending-required-consent";

export function getConsentStatus() {
  return api<ConsentStatus>("/users/me/consent");
}

export function saveConsent() {
  return api<ConsentSaveResponse>("/users/me/consent", {
    method: "PATCH",
    body: JSON.stringify({
      is_consented: true,
      policy_version: CURRENT_CONSENT_VERSION,
    }),
  });
}

export function queueConsentForSync() {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    PENDING_CONSENT_KEY,
    JSON.stringify({ isConsented: true, policyVersion: CURRENT_CONSENT_VERSION }),
  );
}

export function hasQueuedConsent() {
  if (typeof window === "undefined") return false;
  return Boolean(window.localStorage.getItem(PENDING_CONSENT_KEY));
}

export function clearQueuedConsent() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(PENDING_CONSENT_KEY);
}

export async function syncQueuedConsent() {
  if (typeof window === "undefined") return null;

  const raw = window.localStorage.getItem(PENDING_CONSENT_KEY);
  if (!raw) return null;

  try {
    const queued = JSON.parse(raw) as { isConsented: boolean; policyVersion: string };
    if (!queued.isConsented) {
      clearQueuedConsent();
      return null;
    }

    const result = await saveConsent();
    clearQueuedConsent();
    return result.consent;
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      clearQueuedConsent();
    }
    throw err;
  }
}
