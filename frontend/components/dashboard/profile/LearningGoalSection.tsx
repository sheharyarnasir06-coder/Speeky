"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { LEARNING_GOALS, getLearningGoal, setLearningGoal, type LearningGoal } from "@/lib/goals";

/**
 * US-10: Dynamic Goal Updating. No `goal` field exists on the backend User
 * model yet, so this persists to localStorage — see lib/goals.ts for the
 * backend TODO. The Home dashboard reads the same value to reorder/reframe
 * content around it (see app/dashboard/page.tsx), which is what satisfies
 * the "dashboard reorders instantly" acceptance criterion without a
 * network round trip.
 */
export function LearningGoalSection() {
  const { user } = useAuth();
  const [selected, setSelected] = React.useState<LearningGoal | null>(null);
  const [saved, setSaved] = React.useState<LearningGoal | null>(null);

  React.useEffect(() => {
    if (!user) return;
    const current = getLearningGoal(user.id);
    setSelected(current);
    setSaved(current);
  }, [user]);

  if (!user || !selected) return null;

  const hasChanges = selected !== saved;

  function handleUpdate() {
    if (!user || !selected) return;
    setLearningGoal(user.id, selected);
    setSaved(selected);
    toast.success(
      `Focus area updated — now prioritizing ${LEARNING_GOALS.find((g) => g.id === selected)?.label}.`,
    );
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <Target className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Learning Goal</h2>
          <p className="text-sm text-muted-foreground">
            Your dashboard and recommended scenarios prioritize this focus area.
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
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

      <Button
        type="button"
        size="sm"
        className="mt-4"
        disabled={!hasChanges}
        onClick={handleUpdate}
      >
        Update Profile
      </Button>
    </div>
  );
}
