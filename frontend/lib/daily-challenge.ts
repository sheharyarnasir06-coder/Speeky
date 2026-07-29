import { api } from "./api";
import type { OveruseNudgePayload } from "./overuse";

/** Daily Challenge (PDG-US-11): redirects into a real AI Conversation session and
 *  completes on elapsed time since the first prompt in that session — see
 *  Backend/services/daily_challenge_service.py for the timer/credit logic. */

export type ChallengeStatus = "pending" | "qualified";

export interface StartChallengeResponse {
  session_id: string; // AI Conversation session id — redirect the user here
  topic_key: string;
  topic_label: string;
  opening_message: string;
  already_completed_today: boolean;
}

export interface ChallengeConversationStatus {
  session_id: string;
  status: ChallengeStatus;
  just_completed: boolean; // true exactly once: the poll that crossed the 5-minute mark
  seconds_remaining: number;
  current_streak: number;
  longest_streak: number;
  milestone_days: number | null;
  milestone_message: string | null;
  overuse_nudge: OveruseNudgePayload | null;
}

export interface StreakResponse {
  user_id: string;
  current_streak: number;
  longest_streak: number;
  qualified_dates: string[];
}

export function startDailyChallenge(localDate: string) {
  return api<StartChallengeResponse>("/daily-challenge/start", {
    method: "POST",
    body: JSON.stringify({ local_date: localDate }),
  });
}

export function getChallengeConversationStatus(sessionId: string, localDate: string) {
  return api<ChallengeConversationStatus>(
    `/daily-challenge/conversation-status?session_id=${encodeURIComponent(sessionId)}&local_date=${encodeURIComponent(localDate)}`
  );
}

export function getDailyChallengeStreak() {
  return api<StreakResponse>("/daily-challenge/streak");
}
