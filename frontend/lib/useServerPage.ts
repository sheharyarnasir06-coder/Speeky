"use client";

import * as React from "react";

export type PageDirection = "forward" | "back";

/**
 * Generic server-side pagination. Owns the current offset and the last-fetched
 * page; the caller supplies a stable `fetcher(offset, limit)` and does the
 * offset math (so different UIs — a sliding window vs. prev/next — can share this).
 *
 * - Refetches page 0 whenever `fetcher` identity changes (e.g. a filter switch).
 * - `reload()` forces a refetch of the current view (e.g. after a new record).
 * - `direction` is exposed so the caller can pick a slide animation.
 */
export function useServerPage<T>(
  fetcher: (offset: number, limit: number) => Promise<T>,
  limit: number,
) {
  const [offset, setOffset] = React.useState(0);
  const [data, setData] = React.useState<T | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [direction, setDirection] = React.useState<PageDirection>("forward");
  const [nonce, setNonce] = React.useState(0);

  const load = React.useCallback(
    (nextOffset: number, dir: PageDirection) => {
      const target = Math.max(0, nextOffset);
      setLoading(true);
      setDirection(dir);
      return fetcher(target, limit)
        .then((result) => {
          setData(result);
          setOffset(target);
          return result;
        })
        .finally(() => setLoading(false));
    },
    [fetcher, limit],
  );

  // Fetch page 0 on mount, whenever the fetcher changes, and on manual reload.
  React.useEffect(() => {
    void load(0, "forward");
  }, [load, nonce]);

  const goTo = React.useCallback(
    (nextOffset: number, dir: PageDirection = "forward") => load(nextOffset, dir),
    [load],
  );
  const top = React.useCallback(() => load(0, "back"), [load]);
  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  return { offset, limit, data, loading, direction, goTo, top, reload };
}
