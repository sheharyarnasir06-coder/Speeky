import { api } from "./api";
import type { AuthUser } from "./auth";

/**
 * Learning-goal selection (US-08, US-10). Persisted on the User row
 * (`users.learningGoal`) and read back with the profile, so the choice
 * survives logout and follows the account across devices — it is picked in
 * signup only AFTER the email OTP is verified, because no user row exists
 * before that point.
 */

export type LearningGoal =
  | "improve_english"
  | "job_interviews"
  | "workplace_communication"
  | "public_speaking";

export interface LearningGoalOption {
  id: LearningGoal;
  label: string;
  description: string;
}

export const LEARNING_GOALS: LearningGoalOption[] = [
  {
    id: "improve_english",
    label: "Improve English",
    description: "Build general fluency and everyday conversation confidence.",
  },
  {
    id: "job_interviews",
    label: "Job Interviews",
    description: "Prepare for behavioral and technical interview questions.",
  },
  {
    id: "workplace_communication",
    label: "Workplace Communication",
    description: "Practice meetings, emails, and professional conversations.",
  },
  {
    id: "public_speaking",
    label: "Public Speaking",
    description: "Build confidence presenting and speaking to groups.",
  },
];

export const GOAL_DASHBOARD_COPY: Record<
  LearningGoal,
  { subtitle: string; preferredCategory?: "Business" | "Social" | "Travel" }
> = {
  improve_english: {
    subtitle: "You've reached 85% fluency overall. Ready for today's challenge?",
  },
  job_interviews: {
    subtitle:
      "You've reached 85% fluency in interview scenarios. Ready to practice?",
    preferredCategory: "Business",
  },
  workplace_communication: {
    subtitle:
      "You've reached 85% fluency in workplace scenarios. Ready for today's meeting practice?",
    preferredCategory: "Business",
  },
  public_speaking: {
    subtitle:
      "You've reached 85% fluency in presentation scenarios. Ready to build confidence on stage?",
  },
};

// E-03 (Goal Selection Abandonment): the column defaults to "improve_english",
// so an abandoned goal step still leaves a usable profile rather than an unset one.
export const DEFAULT_GOAL: LearningGoal = "improve_english";

/** Narrow an arbitrary stored value to a known goal, falling back to the default. */
export function normalizeGoal(value: string | null | undefined): LearningGoal {
  return LEARNING_GOALS.find((goal) => goal.id === value)?.id ?? DEFAULT_GOAL;
}

export function fetchLearningGoal() {
  return api<{ learning_goal: LearningGoal }>("/users/me/learning-goal");
}

/** Persists the goal and returns the refreshed profile, so callers can push it
 *  straight into AuthContext instead of refetching. */
export function saveLearningGoal(goal: LearningGoal) {
  return api<{ user: AuthUser }>("/users/me/learning-goal", {
    method: "PATCH",
    body: JSON.stringify({ learning_goal: goal }),
  });
}
