"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import {
  LEARNING_GOALS,
  normalizeGoal,
  saveLearningGoal,
  type LearningGoal,
} from "@/lib/goals";

/**
 * US-10: Dynamic Goal Updating. Persists to users.learningGoal and pushes the
 * refreshed profile back into AuthContext, so the Home dashboard — which reads
 * the goal off that same context — reorders immediately (see
 * app/dashboard/page.tsx) without a second fetch.
 */
export function LearningGoalSection() {
  const { user, setUser } = useAuth();
  const saved = user ? normalizeGoal(user.learningGoal) : null;
  const [selected, setSelected] = React.useState<LearningGoal | null>(null);
  const [isSaving, setIsSaving] = React.useState(false);

  React.useEffect(() => {
    if (!user) return;
    setSelected(normalizeGoal(user.learningGoal));
  }, [user]);

  if (!user || !selected) return null;

  const hasChanges = selected !== saved;

  async function handleUpdate() {
    if (!selected) return;
    setIsSaving(true);
    try {
      const result = await saveLearningGoal(selected);
      setUser(result.user);
      toast.success(
        `Focus area updated — now prioritizing ${LEARNING_GOALS.find((g) => g.id === selected)?.label}.`,
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Couldn't update your focus area.",
      );
    } finally {
      setIsSaving(false);
    }
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
        loading={isSaving}
        disabled={!hasChanges}
        onClick={() => void handleUpdate()}
      >
        Update Profile
      </Button>
    </div>
  );
}
