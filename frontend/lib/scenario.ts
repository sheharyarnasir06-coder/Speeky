import { api } from "./api";

export interface ScenarioListItem {
  key: string;
  label: string;
  category: string;
  persona: string;
  intent: string;
  goal_type: "roleplay" | "negotiation";
  target_vocab: string[];
}

export interface ScenarioDetail extends ScenarioListItem {}

export interface StartScenarioResult {
  session_id: string;
  scenario_key: string;
  label: string;
  persona: string;
  intent: string;
  target_vocab: string[];
  opening_message: string;
}

export interface ScenarioTurnResult {
  session_id: string;
  reply: string;
  status: "in_progress" | "completed" | "ended_early";
  classification: "ok" | "silence" | "rambling" | "aggressive" | "emergency";
}

export interface ScenarioEndResult {
  session_id: string;
  status: string;
  /** "scored" | "unavailable". politeness and confidence are both null when unavailable:
   *  the offline grader used to return a politeness base of 78 and met_goal = true. */
  scoring_status: "scored" | "unavailable";
  scores: {
    politeness: number | null;
    vocabulary: number | null;
    confidence: number | null;
  };
  vocab_used: string[];
  vocab_missing: string[];
  met_goal: boolean | null;
  summary: string;
  suggestion: string;
  tips: string[];
  original_line: string;
  polished_line: string;
  graded_by: string;
}

export function getScenarios() {
  return api<{ scenarios: ScenarioListItem[] }>("/scenarios/");
}

export interface RecentScenarioSession {
  session_id: string;
  scenario_key: string;
  title: string;
  category: string;
  description: string;
  status: "in_progress" | "completed" | "ended_early";
  met_goal: boolean | null;
  confidence_score: number | null;
  vocabulary_score: number | null;
  started_at: string;
  completed_at: string | null;
}

// Learner Dashboard's "Recent Scenarios" cards — up to the 6 most recently
// started scenario sessions (in progress or completed), most recent first.
export function getRecentScenarioSessions() {
  return api<{ scenarios: RecentScenarioSession[] }>("/scenarios/recent");
}

export function getScenarioDetail(key: string) {
  return api<ScenarioDetail>(`/scenarios/${encodeURIComponent(key)}`);
}

export function startScenarioSession(scenarioKey: string) {
  return api<StartScenarioResult>("/scenarios/start", {
    method: "POST",
    body: JSON.stringify({ scenario_key: scenarioKey }),
  });
}


export function sendScenarioTurn(sessionId: string, message: string) {
  return api<ScenarioTurnResult>(`/scenarios/${sessionId}/turn`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function endScenarioSession(sessionId: string) {
  return api<ScenarioEndResult>(`/scenarios/${sessionId}/end`, {
    method: "POST",
  });
}

export interface ScenarioSessionState {
  session_id: string;
  scenario_key: string;
  status: string;
  turns: { role: string; content: string }[];
  target_vocab: string[];
  vocab_used: string[];
  scores: { politeness: number | null; vocabulary: number | null; confidence: number | null };
  met_goal: boolean | null;
  summary: string | null;
  tips: string[];
  original_line: string | null;
  polished_line: string | null;
  completed_at: string | null;
}

// Raw session state — used to resume an in-progress session (the ?resume= query
// param flow) where the caller needs the actual turns/status, not the end-result
// mapping getScenarioSession() below returns.
export function getScenarioSessionState(sessionId: string) {
  return api<ScenarioSessionState>(`/scenarios/sessions/${sessionId}`);
}

// Used when a session ends on its own (silence auto-close, aggression, medical-emergency
// break) instead of the learner clicking "End Scenario" — same GET the session page already
// polls off of, just mapped into the same shape endScenarioSession() returns.
export async function getScenarioSession(sessionId: string): Promise<ScenarioEndResult> {
  const session = await api<ScenarioSessionState>(`/scenarios/sessions/${sessionId}`);
  return {
    session_id: session.session_id,
    status: session.status,
    // The stored row carries scores but not the status flag, so derive it: a persisted
    // session with no confidence score is one that was never graded.
    scoring_status: session.scores.confidence === null ? "unavailable" : "scored",
    scores: session.scores,
    vocab_used: session.vocab_used,
    vocab_missing: session.target_vocab.filter((w) => !session.vocab_used.includes(w)),
    met_goal: session.met_goal,
    summary: session.summary ?? "",
    suggestion: session.tips?.[0] ?? "",
    tips: session.tips ?? [],
    original_line: session.original_line ?? "",
    polished_line: session.polished_line ?? "",
    graded_by: "",
  };
}

// ── Admin: custom scenario CRUD (SBL-US-06, CM-US-01 .. CM-US-07) ───────────
export type ScenarioDifficulty = "beginner" | "intermediate" | "advanced";
export type ScenarioStatus = "ACTIVE" | "ARCHIVED";

export interface QualityFeedback {
  breakdown: Record<string, number>;
  recommendations: string[];
  source: "llm" | "offline";
}

export interface ConfidenceFeedback {
  explanation: string;
  warnings: string[];
  guardrail_suggestions: string[];
  source: "llm" | "offline";
}

// Body of the 400 response when create/update is blocked by the publish gate
// (CM-US-02/06/07) — `gate: "not_tested"` is never bypassable; `"needs_acknowledgment"`
// can be resubmitted with `quality_acknowledged: true`.
export interface PublishGateError {
  error: string;
  gate: "not_tested" | "needs_acknowledgment";
  quality_score?: number;
  confidence_score?: number;
  quality_recommendations?: string[];
  confidence_warnings?: string[];
  guardrail_suggestions?: string[];
  readiness_missing?: string[];
}

export interface ReadinessChecklist {
  ready: boolean;
  score: number;
  checks: Record<string, boolean>;
  missing: string[];
}

export interface CustomScenario {
  id: string;
  title: string;
  category: string;
  persona: string;
  intent: string;
  system_prompt: string;
  opening_line: string | null;
  target_vocab: string[];
  goal_type: "roleplay" | "negotiation";
  difficulty: ScenarioDifficulty;
  safety_mode: boolean;
  corporate_tone: boolean;
  status: ScenarioStatus;
  archived_at: string | null;
  version: number;
  sandbox_tested: boolean;
  quality_score: number | null;
  quality_feedback: QualityFeedback | null;
  confidence_score: number | null;
  confidence_feedback: ConfidenceFeedback | null;
  scored_at: string | null;
  readiness_score: number | null;
  readiness_checklist: ReadinessChecklist | null;
  created_at: string;
  updated_at: string;
}

export interface CustomScenarioInput {
  title: string;
  category: string;
  persona: string;
  intent: string;
  system_prompt: string;
  opening_line?: string;
  target_vocab: string[];
  goal_type: "roleplay" | "negotiation";
  difficulty: ScenarioDifficulty;
  safety_mode: boolean;
  corporate_tone: boolean;
  tested: boolean;
  quality_acknowledged: boolean;
}

export interface ScenarioVersionEntry {
  version: number;
  snapshot: Record<string, unknown>;
  created_at: string;
}

export function adminListCustomScenarios() {
  return api<{ scenarios: CustomScenario[] }>("/scenarios/admin/custom");
}

export function adminCreateCustomScenario(data: CustomScenarioInput) {
  return api<CustomScenario>("/scenarios/admin/custom", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function adminUpdateCustomScenario(id: string, data: CustomScenarioInput) {
  return api<CustomScenario>(`/scenarios/admin/custom/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// Archives rather than hard-deletes (CM-US-04 E-03) — kept for anyone still
// mid-session, hidden from new learner sessions, restorable by an admin.
export function adminArchiveCustomScenario(id: string) {
  return api<CustomScenario>(`/scenarios/admin/custom/${id}`, {
    method: "DELETE",
  });
}

export function adminRestoreCustomScenario(id: string) {
  return api<CustomScenario>(`/scenarios/admin/custom/${id}/restore`, {
    method: "POST",
  });
}

export function adminListScenarioVersions(id: string) {
  return api<{ current_version: number; versions: ScenarioVersionEntry[] }>(
    `/scenarios/admin/custom/${id}/versions`,
  );
}

export function adminRollbackCustomScenario(id: string, version: number) {
  return api<CustomScenario>(`/scenarios/admin/custom/${id}/rollback/${version}`, {
    method: "POST",
  });
}

// CM-US-02 / CM-US-06: one combined LLM call scoring both Template Quality and
// Prompt Confidence.
export function adminEvaluateTemplate(id: string) {
  return api<CustomScenario>(`/scenarios/admin/custom/${id}/evaluate`, {
    method: "POST",
  });
}

// CM-US-07: deterministic readiness checklist (auto-runs evaluate first if unscored).
export function adminAssessReadiness(id: string) {
  return api<CustomScenario>(`/scenarios/admin/custom/${id}/readiness`, {
    method: "POST",
  });
}

// Sandbox tester (SBL-US-06 E-01) — try the current unsaved form values against the
// AI before publishing. No DB row, no learner-facing effect.
export interface ScenarioPreviewTurn {
  role: "user" | "assistant";
  content: string;
}

export function previewCustomScenario(data: {
  /** CM-US-14 (US-198): attributes this sandbox run to a SAVED scenario so it
   *  counts toward its sandbox success rate. Omit for an unsaved draft. */
  scenario_id?: string;
  persona: string;
  system_prompt: string;
  opening_line?: string;
  target_vocab: string[];
  goal_type: "roleplay" | "negotiation";
  safety_mode: boolean;
  corporate_tone: boolean;
  turns: ScenarioPreviewTurn[];
  message?: string;
}) {
  return api<{ reply: string; classification: string }>("/scenarios/admin/preview", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
// ===========================================================================
// Sprint 3 — Content Intelligence
// US-192 Vocabulary Coverage · US-193 Template Performance · US-195 Prompt
// Explainability · US-196 Content Drift · US-198 Deployment Confidence
//
// GET returns the cached result (cheap, no LLM call); POST recomputes. The admin
// UI reads on open and only recomputes on an explicit click, so opening a panel
// never costs an LLM request.
// ===========================================================================

/** CM-US-08 exception flags. */
export type VocabCoverageFlag =
  | "excessive_repetition"
  | "vocabulary_gaps"
  | "incorrect_difficulty"
  | "domain_mismatch";

export interface VocabCoverageResult {
  scenario_id: string;
  coverage_score: number;
  breakdown: {
    topic_relevance: number;
    difficulty_distribution: number;
    redundancy: number;
    coverage_completeness: number;
  };
  flags: VocabCoverageFlag[];
  recommendations: string[];
  suggested_additions: string[];
  redundant_words: string[];
  _source: "llm" | "offline" | "empty";
  _note?: string;
}

export function adminGetVocabCoverage(id: string) {
  return api<{
    scenario_id: string;
    coverage_score: number | null;
    feedback: Omit<VocabCoverageResult, "scenario_id" | "coverage_score"> | null;
    scored_at: string | null;
    stale: boolean;
  }>(`/scenarios/admin/custom/${id}/vocab-coverage`);
}

export function adminScoreVocabCoverage(id: string) {
  return api<VocabCoverageResult>(`/scenarios/admin/custom/${id}/vocab-coverage`, {
    method: "POST",
  });
}

/** CM-US-11. `source: "synthesised"` means the model skipped this deduction and
 *  the server filled it in to keep "every deduction explained" true. */
export interface ExplainabilityDeduction {
  dimension: string;
  label: string;
  score: number;
  points_lost: number;
  explanation: string;
  source: "ai" | "synthesised";
}

export interface ExplainabilityReport {
  summary: string;
  strengths: string[];
  weaknesses: string[];
  ambiguous_wording: { phrase: string; why: string }[];
  missing_constraints: string[];
  suggested_improvements: string[];
  deductions: ExplainabilityDeduction[];
  overlapping_issues: { theme: string; count: number; detail: string }[];
  minimal_issues: boolean;
  /** Model's confidence in its OWN analysis: high = trustworthy. */
  analysis_confidence: number;
  low_confidence: boolean;
  quality_score: number | null;
  confidence_score: number | null;
  _source: "llm" | "offline";
}

export function adminGetExplanation(id: string) {
  return api<{ scenario_id: string; report: ExplainabilityReport | null; generated_at: string | null; stale: boolean }>(
    `/scenarios/admin/custom/${id}/explain`,
  );
}

export function adminExplainPrompt(id: string) {
  return api<ExplainabilityReport & { scenario_id: string }>(
    `/scenarios/admin/custom/${id}/explain`,
    { method: "POST" },
  );
}

/** CM-US-09. Every metric is nullable: null means "no data", which is a
 *  different fact from 0 and must never be rendered as one. */
export interface TemplateMetrics {
  usage_count: number;
  completion_rate: number | null;
  average_learner_score: number | null;
  confidence_improvement: number | null;
  vocabulary_success_rate: number | null;
  session_abandonment: number | null;
  learner_satisfaction: number | null;
  satisfaction_responses?: number;
  sample_size: number;
  insufficient_data: boolean;
  newly_published: boolean;
  no_analytics: boolean;
  archived?: boolean;
}

export interface TemplatePerformanceRow {
  scenario_id: string;
  title: string;
  category: string;
  status: ScenarioStatus;
  version: number;
  created_at: string;
  metrics: TemplateMetrics;
}

export function adminPerformanceOverview() {
  return api<{ templates: TemplatePerformanceRow[]; count: number }>(
    "/content-intelligence/performance",
  );
}

export function adminPerformanceDetail(id: string) {
  return api<{
    scenario_id: string;
    title: string;
    status: ScenarioStatus;
    metrics: TemplateMetrics;
    trend: { captured_at: string; sample_size: number; metrics: TemplateMetrics }[];
  }>(`/scenarios/admin/custom/${id}/performance`);
}

export function adminCapturePerformanceSnapshot(id: string) {
  return api<{ id: string; captured_at: string; metrics: TemplateMetrics }>(
    `/scenarios/admin/custom/${id}/performance/snapshot`,
    { method: "POST" },
  );
}

/** CM-US-12. */
export interface DriftSignal {
  label: string;
  baseline: number | null;
  recent: number | null;
  delta: number | null;
  magnitude: number;
  degraded: boolean;
  no_data: boolean;
}

export interface DriftAnalysis {
  scenario_id: string;
  title: string;
  status: "analysed" | "insufficient_data";
  recent_sessions: number;
  baseline_sessions: number;
  required_per_window?: number;
  severity: "INFO" | "WARNING" | "CRITICAL" | null;
  signals: Record<string, DriftSignal>;
  degraded: string[];
  summary?: string;
  suppressed_reason?: "platform_wide";
}

export interface DriftAlert {
  id: string;
  scenario_id: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  summary: string;
  signals: { degraded: string[]; detail: Record<string, DriftSignal> };
  status: "OPEN" | "ACKNOWLEDGED";
  detected_at: string;
  acknowledged_at: string | null;
}

export function adminDriftOverview() {
  return api<{
    analyses: DriftAnalysis[];
    alerts: DriftAlert[];
    alerts_created: number;
    platform_wide_signals: string[];
  }>("/content-intelligence/drift");
}

export function adminAcknowledgeDriftAlert(alertId: string) {
  return api<{ id: string; status: string; acknowledged_at: string }>(
    `/content-intelligence/drift/alerts/${alertId}/acknowledge`,
    { method: "POST" },
  );
}

/** CM-US-14. `blocking` is a hard stop (E-02); `warnings` are advisory
 *  (E-01/E-03/E-05/E-06) and never prevent a deploy on their own. */
export interface DeploymentException {
  code: string;
  title: string;
  detail: string;
  resolution: string;
}

export interface DeploymentConfidence {
  scenario_id: string;
  version: number;
  confidence_score: number;
  breakdown: {
    prompt_stability: number;
    persona_consistency: number;
    vocabulary_coverage: number;
    expected_ai_behavior: number;
    sandbox_success_rate: number;
    deployment_history: number;
  };
  blocking: DeploymentException[];
  warnings: DeploymentException[];
  recommendation: string;
  requires_review: boolean;
  can_deploy: boolean;
  sandbox_runs: number;
  sandbox_passes: number;
  previous_deployments: number;
}

export interface DeploymentRecord {
  id: string;
  version: number;
  confidence_score: number;
  breakdown: Record<string, number>;
  outcome: "DEPLOYED" | "BLOCKED" | "ROLLED_BACK";
  note: string;
  created_at: string;
}

export function adminDeploymentConfidence(id: string) {
  return api<DeploymentConfidence>(`/scenarios/admin/custom/${id}/deployment-confidence`, {
    method: "POST",
  });
}

export function adminDeploymentHistory(id: string) {
  return api<{ scenario_id: string; current_version: number; deployments: DeploymentRecord[] }>(
    `/scenarios/admin/custom/${id}/deployments`,
  );
}

/** CM-US-09 "Learner satisfaction" / CM-US-12 "user feedback". Always optional. */
export function rateScenarioSession(sessionId: string, rating: number) {
  return api<{ session_id: string; satisfaction_rating: number }>(
    `/scenarios/sessions/${sessionId}/rating`,
    { method: "POST", body: JSON.stringify({ rating }) },
  );
}
