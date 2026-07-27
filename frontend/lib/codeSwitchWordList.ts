import { api } from "./api";

// US-152: Code-Switch Personal Word List — the REAL backend feature
// (routers/code_switch_routes.py -> services/code_switch_service.py ->
// lib/code_switch/word_list_store.py). Not to be confused with
// lib/code-switch.ts, which is the unrelated US-59 sensitivity-settings
// shim CodeSwitchSection.tsx already used.

export interface CodeSwitchedWord {
  word: string;
  english_equivalent: string;
  context_sentences: string[];
  frequency: number;
  ignored: boolean;
  first_seen: string | null;
}

export interface CodeSwitchWordListResponse {
  words: CodeSwitchedWord[];
  total: number;
  empty_state_message: string | null; // E-03
}

export function getCodeSwitchWordList() {
  return api<CodeSwitchWordListResponse>("/code-switch/word-list");
}

export function ignoreCodeSwitchWord(word: string) {
  return api<{ success: boolean; word: string; ignored: boolean }>(
    `/code-switch/word-list/${encodeURIComponent(word)}/ignore`,
    { method: "PATCH" }
  );
}

export function removeCodeSwitchWord(word: string) {
  return api<{ success: boolean; word: string; removed: boolean }>(
    `/code-switch/word-list/${encodeURIComponent(word)}`,
    { method: "DELETE" }
  );
}
