import { api } from "./api";

// ── Accent Calibration API (prefix: /api/users) ──────────────────────────────
// Routes from: backend/routers/user_routes.py
// GET  /api/users/me/accent-preference
// PATCH /api/users/me/accent-preference
// POST /api/accent-assessment/sub-dialect-dispute
//
// Mirrors backend/services/accent_calibration_service.py's VALID_SUB_DIALECTS.
// "broad_regional" is a frontend-only sentinel for "no sub-dialect selected" —
// the backend only ever accepts one of the 5 values below or null/omitted,
// never the literal string "broad_regional" (sending it raises a ValueError).
export type SubDialect = "punjabi" | "sindhi" | "pashto" | "balochi" | "kashmiri";

export interface AccentPreferenceResponse {
  accent_model_preference: "generic_global" | "south_asian_pakistani";
  sub_dialect_preference?: SubDialect | null;
  // Server-computed notice: low-confidence-dialect fallback warning (ACC-US-09
  // E-01) or a "beta refinement" confirmation for an active sub-dialect.
  notice?: string | null;
}

export interface UpdateAccentPreferenceInput {
  accent_model_preference: "generic_global" | "south_asian_pakistani";
  sub_dialect_preference?: SubDialect | null;
}

export interface SubDialectDisputeResult {
  status: string;
  message: string;
}

// GET /api/users/me/accent-preference
export function getAccentPreference() {
  return api<AccentPreferenceResponse>("/users/me/accent-preference");
}

// PATCH /api/users/me/accent-preference
export function updateAccentPreference(data: UpdateAccentPreferenceInput) {
  return api<AccentPreferenceResponse>("/users/me/accent-preference", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// POST /api/accent-assessment/sub-dialect-dispute
export function submitSubDialectDispute(reason?: string) {
  return api<SubDialectDisputeResult>("/accent-assessment/sub-dialect-dispute", {
    method: "POST",
    body: JSON.stringify({ dispute_reason: reason }),
  });
}
