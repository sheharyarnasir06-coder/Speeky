import { api } from "./api";
import type { VoiceTokenResult } from "./useLiveKitVoice";

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

export function getScenarioDetail(key: string) {
  return api<ScenarioDetail>(`/scenarios/${encodeURIComponent(key)}`);
}

export function startScenarioSession(scenarioKey: string) {
  return api<StartScenarioResult>("/scenarios/start", {
    method: "POST",
    body: JSON.stringify({ scenario_key: scenarioKey }),
  });
}

export function getScenarioVoiceToken(sessionId: string) {
  return api<VoiceTokenResult>(`/scenarios/${sessionId}/voice-token`, {
    method: "POST",
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