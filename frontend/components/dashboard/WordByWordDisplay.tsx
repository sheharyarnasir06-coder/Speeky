"use client";

import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// "correct"/"mispronounced"/"stress_error"/"skipped" mirror backend WordStatus
// (lib/text_alignment.py) — the authoritative, post-upload classification used by both
// Pronunciation Coach's attempt result and Accent Assessment's assessment result.
// "wrong"/"pending" are live-preview-only (lib/usePronunciationLivePreview.ts's cheap
// client-side compare while still recording, before the real result lands).
export type WordDisplayStatus = "correct" | "mispronounced" | "stress_error" | "skipped" | "wrong" | "pending";

export interface WordDisplayItem {
  word: string;
  status: WordDisplayStatus;
  /** Wrong 3+ times in a row (Pronunciation Coach only) — the pill itself glows to
   * draw the eye, so practicing it doesn't need a separate callout box. */
  stuck?: boolean;
}

const STATUS_CLASSES: Record<WordDisplayStatus, string> = {
  correct: "cursor-default bg-success/15 text-success",
  mispronounced: "cursor-pointer bg-danger/15 text-danger hover:bg-danger/25",
  stress_error: "cursor-pointer bg-danger/15 text-danger hover:bg-danger/25",
  // Missed/skipped gets its own color rather than blending into "wrong" — amber is the
  // closest semantic token to "yellow" this theme has (no dedicated yellow exists).
  skipped: "cursor-pointer bg-warning/15 text-warning hover:bg-warning/25",
  // Live-preview only, softer than the authoritative colors above (/10 not /15) — the
  // live guess can still change on the next partial, so it should read as a hint, not
  // a verdict. Same hues, no new colors, just lower intensity while it's still live.
  wrong: "cursor-default bg-danger/10 text-danger",
  pending: "cursor-default bg-muted/40 text-muted-foreground",
};

interface WordByWordDisplayProps {
  words: WordDisplayItem[];
  /** Omit for a read-only display (Accent Assessment's result has no per-word retry). */
  onWordClick?: (word: string) => void;
  selectedWord?: string | null;
  /** One-time attention arrow above this exact word — shown the moment it first
   * crosses into "stuck", cleared on the next interaction, never shown again. */
  pointedWord?: string | null;
  className?: string;
}

export function WordByWordDisplay({ words, onWordClick, selectedWord, pointedWord, className }: WordByWordDisplayProps) {
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {words.map((w, i) => {
        const clickable = Boolean(onWordClick) && w.status !== "correct";
        return (
          <div key={`${w.word}-${i}`} className="relative">
            {pointedWord === w.word ? (
              <ChevronDown
                className="absolute -top-5 left-1/2 h-5 w-5 -translate-x-1/2 animate-bounce text-warning motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : null}
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onWordClick?.(w.word)}
              className={cn(
                "rounded-full px-3 py-1 text-sm font-medium transition-all",
                STATUS_CLASSES[w.status],
                w.stuck ? "animate-pulse ring-2 ring-warning ring-offset-1 motion-reduce:animate-none" : "",
                selectedWord === w.word && clickable ? "ring-2 ring-danger ring-offset-1" : "",
              )}
            >
              {w.word}
            </button>
          </div>
        );
      })}
    </div>
  );
}
