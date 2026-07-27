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

// ── Admin: custom scenario CRUD (SBL-US-06) ─────────────────────────────────
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
  safety_mode: boolean;
  corporate_tone: boolean;
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
  safety_mode: boolean;
  corporate_tone: boolean;
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

export function adminDeleteCustomScenario(id: string) {
  return api<null>(`/scenarios/admin/custom/${id}`, {
    method: "DELETE",
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