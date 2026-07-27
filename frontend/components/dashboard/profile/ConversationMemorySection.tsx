"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Brain, Trash2 } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api";
import {
  deleteMemoryFact,
  listMemoryFacts,
  setMemoryOptOut,
  type MemoryFact,
} from "@/lib/conversation";

/** AIC-US-06: cross-session personalization memory, self-service management. */
export function ConversationMemorySection() {
  const [facts, setFacts] = React.useState<MemoryFact[] | null>(null);
  const [optedOut, setOptedOut] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    listMemoryFacts()
      .then((data) => setFacts(data.facts))
      .catch(() => {
        setFacts([]);
        toast.error("Couldn't load conversation memory.");
      });
  }, []);

  async function handleOptOut(enabled: boolean) {
    setError(null);
    try {
      const result = await setMemoryOptOut(enabled);
      setOptedOut(result.opted_out);
      setFacts(result.facts);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  async function handleDelete(factId: string) {
    setError(null);
    try {
      await deleteMemoryFact(factId);
      setFacts((prev) => prev?.filter((f) => f.fact_id !== factId) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
            <Brain className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-foreground">Conversation Memory</h2>
            <p className="text-sm text-muted-foreground">
              Facts your AI coach remembers across conversation sessions.
            </p>
          </div>
        </div>
        <Switch
          checked={!optedOut}
          onCheckedChange={(checked) => handleOptOut(!checked)}
          label="Remember facts across sessions"
          hideLabel
        />
      </div>

      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

      {facts && facts.length > 0 ? (
        <ul className="mt-4 flex flex-col gap-2">
          {facts.map((fact) => (
            <li
              key={fact.fact_id}
              className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-3 py-2 text-sm"
            >
              <span className="text-foreground">
                <span className="text-muted-foreground">{fact.category}:</span> {fact.value}
              </span>
              <button
                type="button"
                onClick={() => handleDelete(fact.fact_id)}
                aria-label="Forget this"
                className="text-muted-foreground hover:text-danger"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">
          Nothing remembered yet — facts appear here after a few conversation sessions.
        </p>
      )}
    </div>
  );
}
