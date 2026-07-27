"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api";
import { submitAccentAssessment, type SubmitAccentAssessmentInput } from "@/lib/accentProgress";

interface ScoreField {
  key: keyof SubmitAccentAssessmentInput;
  label: string;
}

const SCORE_FIELDS: ScoreField[] = [
  { key: "pronunciation_score", label: "Pronunciation" },
  { key: "word_stress_score", label: "Word Stress" },
  { key: "intonation_score", label: "Intonation" },
  { key: "clarity_score", label: "Clarity" },
];

const DEFAULT_SCORES: SubmitAccentAssessmentInput = {
  pronunciation_score: 65,
  word_stress_score: 65,
  intonation_score: 65,
  clarity_score: 65,
};

interface AccentCheckInModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

/** Minimal submission surface for an Accent Assessment check-in — feeds ACC-US-15's tracker. */
export function AccentCheckInModal({ open, onClose, onSuccess }: AccentCheckInModalProps) {
  const [scores, setScores] = React.useState<SubmitAccentAssessmentInput>(DEFAULT_SCORES);
  const [error, setError] = React.useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);

  function handleClose() {
    setScores(DEFAULT_SCORES);
    setError(null);
    onClose();
  }

  async function handleSubmit() {
    setError(null);
    setIsSubmitting(true);
    try {
      await submitAccentAssessment(scores);
      setScores(DEFAULT_SCORES);
      onSuccess();
      toast.success("Accent check-in logged.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={isSubmitting ? () => {} : handleClose}
      title="Accent Check-In"
      description="Log this month's accent scores to keep your Progress Tracker up to date."
    >
      <div className="flex flex-col gap-5">
        {SCORE_FIELDS.map((field) => (
          <div key={field.key} className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-sm">
              <label htmlFor={field.key} className="font-medium text-foreground">
                {field.label}
              </label>
              <span className="font-semibold text-primary">{scores[field.key]}%</span>
            </div>
            <input
              id={field.key}
              type="range"
              min={0}
              max={100}
              value={scores[field.key]}
              onChange={(event) =>
                setScores((prev) => ({ ...prev, [field.key]: Number(event.target.value) }))
              }
              className="h-2 w-full cursor-pointer rounded-full bg-muted"
            />
          </div>
        ))}

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <div className="flex items-center gap-3">
          <Button type="button" size="sm" loading={isSubmitting} onClick={handleSubmit}>
            Submit Check-In
          </Button>
          <Button type="button" variant="ghost" size="sm" disabled={isSubmitting} onClick={handleClose}>
            Cancel
          </Button>
        </div>
      </div>
    </Modal>
  );
}
