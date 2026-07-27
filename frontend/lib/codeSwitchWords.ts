import { api } from "./api";

// CSC-US-01 personalized "common code-switch words" practice tracker. Populated when
// Workplace Coaching flags a code-switched word (backend services/code_switch_service.py).
// Distinct from lib/code-switch.ts, which is the (separate) sensitivity-settings shim.

export interface CodeSwitchWord {
  id: string;
  word: string;
  suggestion: string;
  count: number;
  last_seen_at: string;
}

export function getCodeSwitchWords() {
  return api<{ words: CodeSwitchWord[]; total: number }>("/coaching/code-switch-words");
}

export function deleteCodeSwitchWord(wordId: string) {
  return api<{ id: string; deleted: boolean }>(
    `/coaching/code-switch-words/${wordId}`,
    { method: "DELETE" }
  );
}
