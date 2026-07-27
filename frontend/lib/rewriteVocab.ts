import { api } from "./api";

// Vocabulary Mastery Tracking — US-160 / PSA-US-08

export type VocabFilter = "all" | "mastered" | "practicing" | "review";

export interface VocabWord {
  word: string;
  use_count: number;
  status: "introduced" | "practicing" | "mastered";
  needs_review: boolean;
  introduced_from?: string | null;
  last_used_at?: string | null;
}

export interface VocabCounts {
  mastered: number;
  practicing: number;
  review: number;
  total: number;
}

export interface PaginatedVocab {
  counts: VocabCounts;
  mastery_percentage: number;
  is_empty: boolean;
  words: VocabWord[];
  status_filter: VocabFilter;
  total_filtered: number;
  offset: number;
  limit: number;
}

export interface IntroduceVocabResult {
  introduced: string[];
  already_tracked: string[];
  extracted_by: "llm" | "offline";
}

// Seed the advanced words a rewrite introduced onto the learner's list.
export function introduceVocab(original: string, rewrite: string, context?: string) {
  return api<IntroduceVocabResult>("/rewrite-vocab/introduce", {
    method: "POST",
    body: JSON.stringify({ original, rewrite, context: context ?? null }),
  });
}

function vocabQuery(offset: number, limit: number, status: VocabFilter): string {
  return `offset=${offset}&limit=${limit}&status=${status}`;
}

// Current mastery state — paginated, cheap read (no recompute).
export function getVocabMastery(offset = 0, limit = 10, status: VocabFilter = "all") {
  return api<PaginatedVocab>(`/rewrite-vocab/?${vocabQuery(offset, limit, status)}`);
}

// Rescan the learner's practice sessions, recompute mastery, return the fresh page.
export function refreshVocabMastery(offset = 0, limit = 10, status: VocabFilter = "all") {
  return api<PaginatedVocab>(`/rewrite-vocab/refresh?${vocabQuery(offset, limit, status)}`, {
    method: "POST",
  });
}
