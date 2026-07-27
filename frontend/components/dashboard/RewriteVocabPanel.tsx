"use client";

import * as React from "react";
import { GraduationCap, RefreshCw, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  getVocabMastery,
  refreshVocabMastery,
  type PaginatedVocab,
  type VocabFilter,
} from "@/lib/rewriteVocab";
import { useServerPage } from "@/lib/useServerPage";
import { cn } from "@/lib/utils";

const VOCAB_PAGE_SIZE = 10;

const FILTERS: { value: VocabFilter; label: string; countKey: keyof PaginatedVocab["counts"] | "total" }[] = [
  { value: "all", label: "All", countKey: "total" },
  { value: "mastered", label: "Mastered", countKey: "mastered" },
  { value: "practicing", label: "Practicing", countKey: "practicing" },
  { value: "review", label: "To review", countKey: "review" },
];

const STATUS_LABEL: Record<string, string> = {
  mastered: "used 3+×",
  practicing: "used 1–2×",
  introduced: "not used yet",
};

interface Props {
  /** Bump this to force a refetch (e.g. after a new rewrite introduces vocab). */
  refreshSignal?: number;
}

// US-160: paginated Vocabulary Mastery — bucket counts + a 10-per-page word list.
function RewriteVocabPanelImpl({ refreshSignal = 0 }: Props) {
  const [filter, setFilter] = React.useState<VocabFilter>("all");
  const [refreshing, setRefreshing] = React.useState(false);

  const fetcher = React.useCallback(
    (offset: number, limit: number) => getVocabMastery(offset, limit, filter),
    [filter],
  );
  const { offset, limit, data, loading, direction, goTo, reload } = useServerPage<PaginatedVocab>(
    fetcher,
    VOCAB_PAGE_SIZE,
  );

  // Refetch when the parent introduces new vocabulary.
  React.useEffect(() => {
    if (refreshSignal > 0) reload();
  }, [refreshSignal, reload]);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await refreshVocabMastery(0, VOCAB_PAGE_SIZE, filter);
      reload();
    } catch {
      /* best-effort */
    } finally {
      setRefreshing(false);
    }
  }

  if (!data || data.is_empty) return null;

  const { counts, mastery_percentage, words, total_filtered } = data;
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total_filtered;
  const pageStart = total_filtered === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + limit, total_filtered);

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-serif text-lg font-semibold text-foreground">
          <GraduationCap className="h-4 w-4 text-primary" aria-hidden="true" />
          Vocabulary Mastery
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            <span className="font-semibold text-primary">{mastery_percentage}%</span> mastered (
            {counts.mastered}/{counts.total})
          </span>
          <Button variant="outline" size="sm" onClick={handleRefresh} loading={refreshing}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Refresh from my practice
          </Button>
        </div>
      </div>

      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${mastery_percentage}%` }}
        />
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const count = f.countKey === "total" ? counts.total : counts[f.countKey];
          const active = filter === f.value;
          return (
            <button
              key={f.value}
              type="button"
              onClick={() => setFilter(f.value)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "bg-surface text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              {f.label} ({count})
            </button>
          );
        })}
      </div>

      {/* Word list (paginated) */}
      {words.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          No words in this list yet.
        </p>
      ) : (
        <div
          key={`${filter}-${offset}`}
          className={cn(
            "flex flex-wrap gap-1.5",
            direction === "forward" ? "animate-slide-in-right" : "animate-slide-in-left",
          )}
        >
          {words.map((w) => (
            <span
              key={w.word}
              title={`${STATUS_LABEL[w.status] ?? ""}${w.needs_review ? " · needs review" : ""}`}
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-medium",
                w.status === "mastered"
                  ? "bg-primary/10 text-primary"
                  : w.status === "practicing"
                    ? "bg-secondary text-secondary-foreground"
                    : "bg-surface text-muted-foreground",
              )}
            >
              {w.word}
              {w.needs_review ? " ⚠" : ""}
            </span>
          ))}
        </div>
      )}

      {/* Pagination controls */}
      {total_filtered > limit ? (
        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="text-xs text-muted-foreground">
            {pageStart}–{pageEnd} of {total_filtered}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!hasPrev || loading}
              onClick={() => goTo(Math.max(0, offset - limit), "back")}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!hasNext || loading}
              onClick={() => goTo(offset + limit, "forward")}
            >
              Next
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export const RewriteVocabPanel = React.memo(RewriteVocabPanelImpl);
