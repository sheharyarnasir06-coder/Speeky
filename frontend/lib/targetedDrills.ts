import { api } from "./api";

// ── Targeted Drills API (prefix: /api/accent-assessment) ────────────────────
// Routes from: backend/routers/accent_routes.py
// GET  /api/accent-assessment/targeted-drills
// POST /api/accent-assessment/targeted-drills/{drill_id}/submit
// POST /api/accent-assessment/targeted-drills/skip

export interface TargetedDrill {
  drill_id: string;
  target_phoneme: string;
  issue_description: string;
  sentence: string;
  prompt_token: string;
  placement_tip?: string | null;
  is_paused?: boolean;
}

export interface TargetedDrillsResponse {
  drills: TargetedDrill[];
}

export interface TargetedDrillResult {
  drill_id: string;
  target_phoneme: string;
  overall_score: number;
  improved_vs_baseline: boolean;
  baseline_score?: number | null;
  placement_tip?: string | null;
  warning?: string | null;
  model_used?: string;
}

export interface SkipDrillResponse {
  status: string;
  message: string;
}

// GET /api/accent-assessment/targeted-drills
export function getTargetedDrills() {
  return api<TargetedDrillsResponse>("/accent-assessment/targeted-drills");
}

// POST /api/accent-assessment/targeted-drills/{drill_id}/submit  (multipart)
export function submitTargetedDrill(drillId: string, formData: FormData) {
  return api<TargetedDrillResult>(`/accent-assessment/targeted-drills/${drillId}/submit`, {
    method: "POST",
    body: formData,
  });
}

// POST /api/accent-assessment/targeted-drills/skip
export function skipTargetedExercises() {
  return api<SkipDrillResponse>("/accent-assessment/targeted-drills/skip", {
    method: "POST",
  });
}
