import { api } from "./api";
import type { VoiceTokenResult } from "./useLiveKitVoice";

export type InterviewMode = "standard" | "panel" | "case_study" | "multi_round";
export type PersonaTone = "strict_corporate" | "friendly_startup" | "formal_panel" | "neutral";

export interface Panelist {
  name: string;
  persona_tone: PersonaTone;
  focus_area: string;
}

export interface SessionStartResponse {
  session_id: string;
  mode: InterviewMode;
  status: string;
  current_round: string | null;
  opening_question: string;
  started_at: string;
}

export interface AIExchange {
  speaker: string;
  question: string;
  answer?: string | null;
  flags: string[];
}

export interface AnswerResponse {
  session_id: string;
  next_question: string | null;
  next_speaker: string | null;
  flags: string[];
  round_complete: boolean;
  session_complete: boolean;
}

export interface RoundScorecard {
  round_type: InterviewMode;
  scores: Record<string, number>;
  summary: string;
}

export interface SessionFeedback {
  session_id: string;
  mode: InterviewMode;
  closing_message: string;
  round_scorecards: RoundScorecard[];
  overall_score: number;
  actionable_script: string;
  ended_at: string;
}

export interface ShareReviewResponse {
  share_id: string;
  session_id: string;
  shared_with: string;
  share_link: string;
  access_level: string;
  expires_at: string;
  created_at: string;
}

export interface PeerComment {
  comment_id: string;
  share_id: string;
  author_id: string;
  comment_text: string;
  hidden: boolean;
  created_at: string;
}

export function startInterviewSession(data: {
  mode: InterviewMode;
  role_or_major?: string;
  persona_tone?: PersonaTone;
  panelists?: Panelist[];
  case_type?: string;
  case_difficulty?: string;
  rounds?: InterviewMode[];
}) {
  return api<SessionStartResponse>("/interview-coach/sessions", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface InterviewSessionState {
  session_id: string;
  mode: InterviewMode;
  status: string;
  exchanges: AIExchange[];
  current_round_index: number;
  started_at: string;
}

// Resume fallback — sessionStorage is the fast path for the tab that started the
// session, but it doesn't survive a fresh navigation (e.g. clicking Resume from
// the Explore banner in a new tab, or after sessionStorage was cleared).
export function getInterviewCoachSession(sessionId: string) {
  return api<InterviewSessionState>(`/interview-coach/sessions/${sessionId}`);
}

export function getInterviewCoachVoiceToken(sessionId: string) {
  return api<VoiceTokenResult>(`/interview-coach/sessions/${sessionId}/voice-token`, {
    method: "POST",
  });
}

export function submitInterviewAnswer(
  sessionId: string,
  data: { answer_text: string; response_duration_seconds?: number; silence_before_seconds?: number }
) {
  return api<AnswerResponse>(`/interview-coach/sessions/${sessionId}/answer`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function pauseInterviewSession(sessionId: string, reason = "manual") {
  return api<{ session_id: string; status: string; reason: string }>(
    `/interview-coach/sessions/${sessionId}/pause`,
    { method: "POST", body: JSON.stringify({ reason }) }
  );
}

export function resumeInterviewSession(sessionId: string) {
  return api<{ session_id: string; status: string }>(
    `/interview-coach/sessions/${sessionId}/resume`,
    { method: "POST" }
  );
}

export function takeInterviewBreak(sessionId: string) {
  return api<{ session_id: string; break_taken: boolean }>(
    `/interview-coach/sessions/${sessionId}/break`,
    { method: "POST", body: JSON.stringify({}) }
  );
}

export function endInterviewSession(sessionId: string) {
  return api<SessionFeedback>(`/interview-coach/sessions/${sessionId}/end`, {
    method: "POST",
  });
}

export function shareInterviewReview(data: {
  session_id: string;
  recipient_email_or_id: string;
  note?: string;
  expiry_hours?: number;
  access_level?: "transcript_only" | "full";
  content_confirmed?: boolean;
}) {
  return api<ShareReviewResponse>("/interview-coach/reviews", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function addPeerComment(shareId: string, commentText: string) {
  return api<PeerComment>(`/interview-coach/reviews/${shareId}/comments`, {
    method: "POST",
    body: JSON.stringify({ comment_text: commentText }),
  });
}

export function listPeerComments(shareId: string) {
  return api<PeerComment[]>(`/interview-coach/reviews/${shareId}/comments`);
}

export function revokeShare(shareId: string) {
  return api<{ share_id: string; revoked: boolean }>(
    `/interview-coach/reviews/${shareId}/revoke`,
    { method: "POST" }
  );
}

export function reportComment(commentId: string) {
  return api<{ comment_id: string; hidden: boolean; reported_by: string }>(
    `/interview-coach/reviews/comments/${commentId}/report`,
    { method: "POST" }
  );
}
