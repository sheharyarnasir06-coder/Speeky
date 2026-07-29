import { api } from "./api";

// US-82 (Target Accent Selection), US-83 (Score Dispute), US-84 (Profile
// Staleness & Re-Baseline) — all share one backend profile/pipeline (see
// backend/services/accent_assessment_service.py), so this file is the one
// place the frontend talks to that shared pipeline too.

export interface TargetAccentOption {
  id: string;
  label: string;
  description: string;
  scoring_note: string;
}

export interface TargetAccentPreference {
  current_accent_id: string | null;
  history: { accent_id: string; changed_at: string; previous_accent_id: string | null }[];
}

export function listTargetAccents() {
  return api<{ accents: TargetAccentOption[] }>("/accent-assessment/target-accents");
}

export function getTargetAccent() {
  return api<TargetAccentPreference>("/accent-assessment/target-accent");
}

export function selectTargetAccent(accentId: string, localCalibrationActive = false) {
  return api<{
    accent: TargetAccentOption;
    was_unsupported_request: boolean;
    fallback_message: string | null;
    confirmation_message: string;
  }>("/accent-assessment/target-accent", {
    method: "POST",
    body: JSON.stringify({ accent_id: accentId, local_calibration_active: localCalibrationActive }),
  });
}

// Shared profile (baseline + drill history)
export interface AccentAssessmentSummary {
  assessment_id: string;
  timestamp: string;
  overall_score: number;
  metrics: Record<string, number>;
  assessment_type: string;
  is_historical: boolean;
  is_audio_available: boolean;
  notice: string | null;
}

export interface AccentProfile {
  has_profile: boolean;
  target_accent_id?: string;
  last_assessment_at?: string;
  dismiss_count?: number;
  baselines_history: AccentAssessmentSummary[];
  drills_history: AccentAssessmentSummary[];
}

export function getAccentProfile() {
  return api<AccentProfile>("/accent-assessment/profile");
}

// US-84: staleness & re-baseline
export interface StalenessDetails {
  profile_age_days: number;
  is_stale: boolean;
  should_prompt: boolean;
  prompt_message: string | null;
  prompt_frequency: "every_login" | "weekly";
  suggested_rebaseline_type: string;
  notice: string | null;
  last_assessment_at: string | null;
}

export function checkAccentStaleness() {
  return api<StalenessDetails>("/accent-assessment/staleness");
}

export function dismissStalenessPrompt() {
  return api<{ dismiss_count: number; last_dismissed_at: string }>("/accent-assessment/staleness/dismiss", {
    method: "POST",
  });
}

export function rebaselineFromSession(sessionId: string) {
  return api<AccentAssessmentSummary>("/accent-assessment/rebaseline", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

// US-83: score dispute
export interface DisputeReasonOption {
  id: "background_noise" | "misheard_word" | "unfair_penalty" | "other";
  label: string;
}

export const DISPUTE_REASONS: DisputeReasonOption[] = [
  { id: "background_noise", label: "Background noise" },
  { id: "misheard_word", label: "Misheard word" },
  { id: "unfair_penalty", label: "Unfair penalty" },
  { id: "other", label: "Other" },
];

export interface ScoreDispute {
  dispute_id: string;
  assessment_id: string;
  metric_name: string;
  original_score: number;
  reason: string;
  status: string;
  audio_available: boolean;
  created_at: string;
  revised_score: number | null;
  auto_flagged_for_content_team: boolean;
  notification: string | null;
}

export function getDisputes() {
  return api<{ disputes: ScoreDispute[]; remaining_allowance: number; max_daily_allowance: number }>(
    "/accent-assessment/disputes"
  );
}

export function submitDispute(data: { assessment_id: string; metric_name: string; reason: string; user_comment?: string }) {
  return api<{
    success: boolean;
    dispute: ScoreDispute;
    remaining_allowance: number;
    max_daily_allowance: number;
    notice: string | null;
  }>("/accent-assessment/disputes", {
    method: "POST",
    body: JSON.stringify(data),
  });
}


// ── Passage reading + liveness appeal ───────────────────────────────────────
// Restored during the upstream merge: these bindings were dropped when this file
// was overwritten, while app/dashboard/accent-assessment/page.tsx still imports
// them and backend/routers/accent_routes.py still serves the routes.

export interface TargetPassageResponse {
  passage_id: string;
  difficulty: string;
  title: string;
  text: string;
  // Always populated by GET /passages (the route mints a liveness prompt token).
  prompt_token: string;
}

export interface WeakPoint {
  issue: string;
  detail: string;
}

export interface AccentAssessmentResult {
  assessment_id: string;
  passage_id: string;
  overall_score: number;
  pronunciation_score: number;
  stress_score: number;
  rhythm_score: number;
  intonation_score: number;
  clarity_score: number;
  weak_points: WeakPoint[];
  exercises: string[];
  warning?: string | null;
  model_used?: string;
}

// GET /api/accent-assessment/passages
export function getTargetPassage() {
  return api<TargetPassageResponse>("/accent-assessment/passages");
}

// POST /api/accent-assessment/passages/{passage_id}/assessments  (multipart)
export function submitPassageAssessment(passageId: string, formData: FormData) {
  return api<AccentAssessmentResult>(`/accent-assessment/passages/${passageId}/assessments`, {
    method: "POST",
    body: formData,
  });
}

// Shared recording-rejection parser — single implementation lives in lib/pronunciation.
export { rejectionFromError } from "./pronunciation";
export type { RecordingRejected } from "./pronunciation";
