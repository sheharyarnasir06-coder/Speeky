"use client";

import * as React from "react";
import { BookOpen, EyeOff, Trash2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  getCodeSwitchWordList,
  ignoreCodeSwitchWord,
  removeCodeSwitchWord,
  type CodeSwitchedWord,
} from "@/lib/codeSwitchWordList";

/**
 * US-152: Code-Switch Personal Word List. Real backend
 * (/api/code-switch/word-list) — separate from CodeSwitchSection.tsx above,
 * which is the unrelated US-59 sensitivity-settings feature and has no
 * word-list UI to repurpose.
 */
export function CodeSwitchWordListSection() {
  const [words, setWords] = React.useState<CodeSwitchedWord[] | null>(null);
  const [emptyMessage, setEmptyMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyWord, setBusyWord] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    getCodeSwitchWordList()
      .then((data) => {
        setWords(data.words);
        setEmptyMessage(data.empty_state_message);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load your word list."));
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  async function handleIgnore(word: string) {
    setBusyWord(word);
    try {
      await ignoreCodeSwitchWord(word);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update that word.");
    } finally {
      setBusyWord(null);
    }
  }

  async function handleRemove(word: string) {
    setBusyWord(word);
    try {
      await removeCodeSwitchWord(word);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove that word.");
    } finally {
      setBusyWord(null);
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <BookOpen className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Code-Switched Words</h2>
          <p className="text-sm text-muted-foreground">
            Non-English words detected during your AI conversations, with their English
            equivalents — most frequent first.
          </p>
        </div>
      </div>

      {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}

      {words === null ? (
        <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
      ) : words.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {words.map((w) => (
            <li
              key={w.word}
              className="flex flex-col gap-2 rounded-xl border border-border p-3 sm:flex-row sm:items-start sm:justify-between"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground">
                  {w.word} <span className="font-normal text-muted-foreground">→ {w.english_equivalent}</span>
                </p>
                {w.context_sentences.length > 0 ? (
                  <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
                    {w.context_sentences.slice(0, 3).map((sentence, i) => (
                      <li key={i} className="truncate italic">"{sentence}"</li>
                    ))}
                  </ul>
                ) : null}
                <p className="mt-1 text-xs text-muted-foreground">Seen {w.frequency}×</p>
              </div>
              <div className="flex shrink-0 gap-2 self-start">
                <button
                  type="button"
                  disabled={busyWord === w.word}
                  onClick={() => handleIgnore(w.word)}
                  className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-surface disabled:opacity-50"
                >
                  <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
                  Ignore
                </button>
                <button
                  type="button"
                  disabled={busyWord === w.word}
                  onClick={() => handleRemove(w.word)}
                  className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger/10 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
