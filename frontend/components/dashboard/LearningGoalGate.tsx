"use client";

import * as React from "react";
import { Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { LEARNING_GOALS, saveLearningGoal, type LearningGoal } from "@/lib/goals";

/**
 * Blocking fallback for accounts created before US-08's signup goal step existed.
 * Those rows were backfilled with learningGoalSet=false (see the
 * 20260728010000_add_learning_goal_set migration) — this renders in place of the
 * whole dashboard shell (DashboardLayout returns this instead of {children}) until
 * the user submits a real choice, same as the mandatory signup step it stands in for.
 */
export function LearningGoalGate() {
  const { setUser } = useAuth();
  const [selected, setSelected] = React.useState<LearningGoal | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit() {
    if (!selected) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const { user } = await saveLearningGoal(selected);
      setUser(user);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save your goal. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-lg rounded-2xl border border-border bg-surface-elevated p-8 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
            <Target className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h1 className="font-serif text-xl font-semibold text-foreground">
              What&apos;s your main goal?
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              One quick thing before you continue — we&apos;ll tailor your dashboard and
              daily challenge around it. You can change this later from your profile.
            </p>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {LEARNING_GOALS.map((goal) => (
            <button
              key={goal.id}
              type="button"
              onClick={() => setSelected(goal.id)}
              className={cn(
                "rounded-xl border p-4 text-left transition-colors",
                selected === goal.id
                  ? "border-primary bg-secondary"
                  : "border-border hover:bg-surface",
              )}
            >
              <p className="text-sm font-semibold text-foreground">{goal.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">{goal.description}</p>
            </button>
          ))}
        </div>

        {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

        <Button
          type="button"
          size="lg"
          className="mt-5 w-full"
          loading={isSubmitting}
          disabled={!selected}
          onClick={() => void handleSubmit()}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
