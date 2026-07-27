"use client";

import * as React from "react";
import { Flag } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { DISPUTE_REASONS, submitDispute, type DisputeReasonOption } from "@/lib/accentAssessment";

/**
 * US-83 (ACC-US-04): Score Dispute & Manual Feedback Loop. One shared
 * control so every scored metric (fluency/vocabulary/pronunciation/overall)
 * gets the same real "This score seems wrong" action, per the story's
 * acceptance criteria ("available on EVERY scored metric, not just the
 * overall score") — not a one-off built for a single tile.
 */
export function ScoreDisputeButton({
  assessmentId,
  metricName,
  metricLabel,
}: {
  assessmentId: string;
  metricName: string;
  metricLabel: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState<DisputeReasonOption["id"]>("misheard_word");
  const [comment, setComment] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [outcome, setOutcome] = React.useState<string | null>(null);

  async function handleSubmit() {
    setSubmitting(true);
    setOutcome(null);
    try {
      const result = await submitDispute({
        assessment_id: assessmentId,
        metric_name: metricName,
        reason,
        user_comment: comment || undefined,
      });
      setOutcome(result.notice ?? "Thanks — we've logged this for review. You'll be notified once it's checked.");
      setOpen(false);
    } catch (err) {
      setOutcome(err instanceof ApiError ? err.message : "Couldn't submit that dispute.");
    } finally {
      setSubmitting(false);
    }
  }

  if (outcome && !open) {
    return <p className="mt-1 text-[11px] text-muted-foreground">{outcome}</p>;
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
      >
        <Flag className="h-3 w-3" aria-hidden="true" />
        This score seems wrong
      </button>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg border border-border bg-surface p-2 text-left">
      <p className="text-[11px] font-medium text-foreground">Why does the {metricLabel} score seem wrong?</p>
      <div className="flex flex-wrap gap-1">
        {DISPUTE_REASONS.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => setReason(option.id)}
            className={cn(
              "rounded-md border px-2 py-1 text-[10px] font-medium transition-colors",
              reason === option.id ? "border-primary bg-secondary" : "border-border hover:bg-surface-elevated",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        placeholder="Optional details…"
        rows={2}
        className="rounded-md border border-input bg-surface-elevated px-2 py-1 text-[11px] text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
      />
      <div className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={handleSubmit}
          className="rounded-md bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </div>
    </div>
  );
}
