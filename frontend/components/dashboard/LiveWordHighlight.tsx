"use client";

import { cn } from "@/lib/utils";
import type { WordPreviewStatus } from "@/lib/usePronunciationLivePreview";

// Colors in the already-displayed sentence/passage itself instead of WordByWordDisplay's
// separate pill list — same hues as WordByWordDisplay's live "/10" tier (a hint, not a
// verdict), just inline spans so the target text never grows a second, redundant copy
// below it. Pending stays unstyled: highlighting unspoken words would read as an error.
const LIVE_WORD_CLASSES: Record<WordPreviewStatus, string> = {
  pending: "",
  correct: "rounded-sm bg-success/15 text-success",
  wrong: "rounded-sm bg-danger/15 text-danger",
};

interface LiveWordHighlightProps {
  words: string[];
  statuses: WordPreviewStatus[];
}

export function LiveWordHighlight({ words, statuses }: LiveWordHighlightProps) {
  return (
    <>
      {words.map((word, i) => (
        <span key={i} className={cn("transition-colors", LIVE_WORD_CLASSES[statuses[i] ?? "pending"])}>
          {word}
          {i < words.length - 1 ? " " : ""}
        </span>
      ))}
    </>
  );
}
