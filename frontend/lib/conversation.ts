import { api, API_URL, ApiError } from "./api";

export interface ConversationTopic {
  key: string;
  label: string;
}

export interface StartConversationResult {
  session_id: string;
  topic_key: string;
  topic_label: string;
  level: string;
  level_source: string;
  level_stale_warning: string | null;
  opening_message: string;
  started_at: string;
}

export interface VoiceTokenResult {
  url: string;
  token: string;
  room: string;
}

export interface SendMessageResult {
  session_id: string;
  reply: string;
  level: string;
  correction_chip: { original: string; corrected: string; explanation: string } | null;
  flags: string[];
  session_ended: boolean;
}

export interface ConversationTurn {
  role: "user" | "assistant";
  content: string;
  input_mode: string | null;
  correction_chip: { original: string; corrected: string; explanation: string } | null;
  created_at: string;
}

export interface EndConversationResult {
  session_id: string;
  status: string;
  duration_seconds: number;
  fluency_score: number;
  vocabulary_score: number;
  pronunciation_score: number | null;
  level: string;
  new_memory_facts: { category: string; value: string }[];
}

export interface MemoryFact {
  fact_id: string;
  category: string;
  value: string;
  updated_at: string;
}

export interface ConversationSessionSummary {
  session_id: string;
  topic_label: string;
  status: string;
  started_at: string;
  completed_at: string | null;
}

export function listConversationSessions() {
  return api<{ sessions: ConversationSessionSummary[] }>("/conversation/sessions");
}

export function listTopics() {
  return api<{ topics: ConversationTopic[] }>("/conversation/topics");
}

export function checkTopic(topic: string) {
  return api<{ verdict: "safe" | "unsafe" | "vague"; preset_match: string | null; reason: string }>(
    `/conversation/topics/validate?topic=${encodeURIComponent(topic)}`
  );
}

export function startConversation(data: {
  topic_key?: string;
  custom_topic?: string;
  level_override?: string;
  show_corrections?: boolean;
}) {
  return api<StartConversationResult>("/conversation/sessions", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getConversationVoiceToken(sessionId: string) {
  return api<VoiceTokenResult>(
    `/conversation/sessions/${sessionId}/voice-token`,
    {
      method: "POST",
    }
  );
}

export function sendConversationMessage(
  sessionId: string,
  data: {
    text: string;
    input_mode?: string;
    show_corrections?: boolean;
    audio_features?: {
      transcript: string;
      duration_seconds: number;
      word_timings: { word: string; start: number; end: number }[];
    };
  }
) {
  return api<SendMessageResult>(`/conversation/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function endConversationSession(sessionId: string) {
  return api<EndConversationResult>(`/conversation/sessions/${sessionId}/end`, {
    method: "POST",
  });
}

export function getConversationTranscript(sessionId: string) {
  return api<{
    session_id: string;
    topic_label: string;
    status: string;
    turns: ConversationTurn[];
    incomplete: boolean;
  }>(`/conversation/sessions/${sessionId}/transcript`);
}

export function listMemoryFacts() {
  return api<{ facts: MemoryFact[] }>("/conversation/memory");
}

export function deleteMemoryFact(factId: string) {
  return api<{ fact_id: string; deleted: boolean }>(`/conversation/memory/${factId}`, {
    method: "DELETE",
  });
}

export function setMemoryOptOut(enabled: boolean) {
  return api<{ opted_out: boolean; facts: MemoryFact[] }>("/conversation/memory/opt-out", {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

// TTS returns raw audio/wav bytes, not JSON — bypasses the api() wrapper.
export async function synthesizeSpeech(text: string, lengthScale = 1.0): Promise<Blob> {
  const response = await fetch(`${API_URL}/conversation/tts`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, length_scale: lengthScale }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(data?.error ?? "Text-to-speech unavailable", response.status);
  }
  return response.blob();
}
