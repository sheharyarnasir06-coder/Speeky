import { api } from "./api";

/** public_speaking's talking agent is Q&A-only — the backend refuses a "qa" token until the
 *  session reaches qa_phase, because a live agent during the speech would talk over the speaker
 *  and its voice would land in the audio being scored. */
export type LiveCallFeature =
  | "conversation"
  | "interview_coach"
  | "scenario"
  | "coaching"
  | "public_speaking";

/** "idle" is public_speaking's speech phase only: an avatar to speak to that never speaks back,
 *  started with no STT/LLM/TTS at all. The backend gates it on the session still being
 *  in_progress — the exact inverse of the qa_phase window, not a relaxation of it. */
export type LiveCallMode = "qa" | "idle";

export interface LiveCallTokenResult {
  token: string;
  url: string;
  room_name: string;
}

export function fetchLiveCallToken(
  feature: LiveCallFeature,
  sessionId: string,
  mode: LiveCallMode = "qa",
) {
  return api<LiveCallTokenResult>("/live-call/token", {
    method: "POST",
    body: JSON.stringify({ feature, session_id: sessionId, mode }),
  });
}
