import { api } from "./api";

export type ActivityType = "scenario" | "conversation" | "pronunciation" | "interview_coach" | "accent";

export interface RecentActivityItem {
  type: ActivityType;
  activity_id: string;
  title: string;
  subtitle: string;
  status: "in_progress" | "completed" | "ended_early";
  score: number | null;
  score_label: string | null;
  occurred_at: string;
  href: string;
}

// Learner Dashboard's "Recent Activity" feed — last 3 practice sessions across every
// feature (scenario, conversation, pronunciation, interview coach, accent), newest first.
export function getRecentActivity() {
  return api<{ activities: RecentActivityItem[] }>("/active-sessions/recent-activity");
}
