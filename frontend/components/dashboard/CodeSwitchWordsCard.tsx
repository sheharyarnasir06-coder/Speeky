"use client";

import * as React from "react";
import { Languages, X } from "lucide-react";
import {
  deleteCodeSwitchWord,
  getCodeSwitchWords,
  type CodeSwitchWord,
} from "@/lib/codeSwitchWords";

// CSC-US-01: the learner's personal code-switch practice tracker. Each row is a
// non-English word they've mixed into professional English, with the suggested equivalent
// and how often it's come up. Removing a word marks it "mastered".
export function CodeSwitchWordsCard() {
  const [words, setWords] = React.useState<CodeSwitchWord[] | null>(null);

  React.useEffect(() => {
    getCodeSwitchWords()
      .then((data) => setWords(data.words))
      .catch(() => setWords([]));
  }, []);

  async function handleRemove(id: string) {
    setWords((prev) => prev?.filter((w) => w.id !== id) ?? null);
    try {
      await deleteCodeSwitchWord(id);
    } catch {
      // Re-fetch on failure so the UI doesn't drift from the server.
      getCodeSwitchWords().then((data) => setWords(data.words)).catch(() => {});
    }
  }

  // Hide entirely until there's something to practice — no empty-state clutter.
  if (!words || words.length === 0) return null;

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-secondary text-primary">
          <Languages className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="font-serif text-lg font-semibold text-foreground">
            Your Code-Switch Words
          </h2>
          <p className="text-xs text-muted-foreground">
            Local words you&apos;ve mixed into English — practice the professional equivalents.
          </p>
        </div>
      </div>

      <ul className="mt-4 flex flex-col divide-y divide-border">
        {words.map((w) => (
          <li key={w.id} className="flex items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <span className="font-medium text-foreground">{w.word}</span>
              <span className="mx-2 text-muted-foreground">&rarr;</span>
              <span className="text-primary">{w.suggestion}</span>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                {w.count}&times;
              </span>
              <button
                type="button"
                onClick={() => handleRemove(w.id)}
                aria-label={`Mark "${w.word}" as mastered`}
                title="Mark as mastered"
                className="text-muted-foreground transition-colors hover:text-danger"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
