import { api } from "./api";

// ── Types (mirrors Backend/services/assessment_service.py, gating_service.py,
// reassessment_service.py response shapes) ──────────────────────────────────

export interface StartAssessmentQuestion {
  assessment_id: string;
  total_questions: number;
  current_question: string;
  question_index: number;
  question_mode: "text" | "audio";
  estimated_duration_minutes: number;
  is_re_assessment?: boolean;
  // True when start resumed an existing in-progress assessment (browser back/refresh)
  // instead of creating a new one — see assessment_service._begin_assessment.
  resumed?: boolean;
  // True when /restart discarded an unfinishable attempt and issued this fresh one.
  restarted?: boolean;
  discarded_attempts?: number;
}

/** /start can also come back without a question: the previous attempt had every answer
 *  saved but never finished scoring, so the server retried it instead of handing back a
 *  dead question (see assessment_service._begin_assessment). */
export interface StartAssessmentRecovered {
  status: "completed";
  assessment_id: string;
}

export type StartAssessmentResult =
  | StartAssessmentQuestion
  | StartAssessmentRecovered
  | AssessmentProcessing;

/** Narrowing helper: did /start hand back an actual question to answer? */
export function isAssessmentQuestion(
  result: StartAssessmentResult,
): result is StartAssessmentQuestion {
  return !("status" in result);
}

export interface SubmitResponseInProgress {
  status: "in_progress";
  next_question: string | null;
  question_index: number;
  next_question_mode: "text" | "audio" | null;
  previous_result: {
    question_id: string;
    category: string | null;
    is_flagged: boolean;
    flag_reason: string | null;
  };
}

export interface SubmitResponseCompleted {
  status: "completed";
  assessment_id: string;
  confidence_score: number;
  fluency_score: number;
  vocabulary_score: number;
  pronunciation_score: number | null;
  learning_level: string;
  duration_seconds: number;
  is_flagged: boolean;
  flag_reason: string | null;
  regression: { action: string; prompt?: Record<string, unknown> } | null;
}

export type SubmitResponseResult =
  | SubmitResponseInProgress
  | SubmitResponseCompleted
  | AssessmentProcessing;

export interface SkillDetail {
  score: number;
  display: string;
  label: string;
  description: string;
  strength: "strong" | "developing" | "emerging";
}

export interface AssessmentSummary {
  assessment_id: string;
  user_id: string;
  display_name: string;
  completed_at: string;
  learning_level: { level: string; label: string };
  confidence_score: { score: number; display: string; message: string };
  skill_breakdown: {
    fluency: SkillDetail;
    vocabulary: SkillDetail;
    pronunciation?: SkillDetail;
    confidence: SkillDetail;
  };
  positive_framing: {
    title: string;
    subtitle: string;
    message: string;
    highlight: string;
  };
  next_steps: string[];
  is_flagged: boolean;
  flag_reason: string | null;
}

export interface FeatureAccessSummary {
  user_id: string;
  display_name: string;
  assessment_status: "UNASSESSED" | "IN_PROGRESS" | "COMPLETED" | "PLATEAUED";
  access_level: "full_access" | "assessment_required" | "basic_only";
  skip_prompt_count: number;
  show_assessment_prompt: boolean;
  assessment_prompt_message: string | null;
  accessible_features: string[];
  inaccessible_features: string[];
  locked_message: string | null;
}

export interface SkipAttemptResult {
  success: boolean;
  reason?: string;
  can_skip: boolean;
  escalated?: boolean;
  message: string;
  action_required?: "confirm_skip";
  skip_count?: number;
}

export interface ReassessmentEligibility {
  user_id: string;
  eligibility: {
    is_eligible: boolean;
    reason?: string;
    days_until_eligible?: number;
    last_assessment_date?: string;
    scheduled_date?: string;
  };
  should_show_prompt: boolean;
  prompt: { message: string; urgency: string } | null;
  progress_trend:
    | { has_trend_data: false; reason: string }
    | {
        has_trend_data: true;
        assessment_count: number;
        overall_change: number;
        trend_direction: "improving" | "declining" | "stable";
        current_score: number;
        starting_score: number;
      };
  configuration: {
    cycle_days: number;
    early_retake_cooldown_days: number;
    regression_threshold: number;
  };
}

// ── Initial Communication Assessment ─────────────────────────────────────────

export function startAssessment() {
  return api<StartAssessmentResult>("/assessment/start", { method: "POST" });
}

/** Discard an unfinished baseline and get a fresh one. Only valid while no baseline has
 *  completed — the escape hatch for an attempt that can never finish scoring. */
export function restartAssessment() {
  return api<StartAssessmentQuestion>("/assessment/restart", { method: "POST" });
}

export function submitAssessmentResponse(
  assessmentId: string,
  data: {
    text_data: string;
    clipboard_detected?: boolean;
    audio_features?: {
      duration_seconds: number;
      word_timings?: { word: string; start: number; end: number }[];
    };
  }
) {
  return api<SubmitResponseResult>(`/assessment/${assessmentId}/respond`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface AssessmentProcessing {
  status: "processing";
  assessment_id: string;
  message: string;
}

export function getResultsSummary(assessmentId: string) {
  return api<AssessmentSummary | AssessmentProcessing>(
    `/assessment/${assessmentId}/summary`,
  );
}

// ── Feature-Access Gating (US-12) ────────────────────────────────────────────

export function getFeatureAccess() {
  return api<FeatureAccessSummary>("/assessment/access");
}

export function attemptSkipAssessment() {
  return api<SkipAttemptResult>("/assessment/skip", { method: "POST" });
}

export function confirmSkipAssessment() {
  return api<{ success: boolean; status: string; message: string }>(
    "/assessment/skip/confirm",
    { method: "POST" }
  );
}

// ── On-Demand / Periodic Re-Assessment (US-14) ───────────────────────────────

export function getReassessmentEligibility() {
  return api<ReassessmentEligibility>("/assessment/reassessment/eligibility");
}

export function startReassessment(isEarly: boolean) {
  return api<StartAssessmentResult>(
    `/assessment/reassessment/start?is_early=${isEarly}`,
    { method: "POST" }
  );
}

export function dismissReassessmentPrompt() {
  return api<{ success: boolean; dismissed_until: string; message: string }>(
    "/assessment/reassessment/dismiss",
    { method: "POST" }
  );
}
