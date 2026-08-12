"use client";

/**
 * Fetches a Live Call room token and manages the "connecting" state.
 *
 * Extracted from `components/common/LiveCallModal.tsx` so a caller can render the room inline
 * rather than in a modal — Public Speaking wants a side-by-side layout (speaker left, avatar
 * right), which a modal cannot express.
 *
 * The modal keeps its own copy of this logic for now; this hook is the shared piece for new
 * callers, not a refactor of the existing one.
 */

import * as React from "react";

import { fetchLiveCallToken, type LiveCallFeature, type LiveCallMode } from "./liveCall";
import { stopCurrent } from "./tts";

export interface LiveCallConnection {
  token: string;
  url: string;
}

export interface UseLiveCallConnectionResult {
  connection: LiveCallConnection | null;
  connecting: boolean;
  /** Only covers the token request. Anything that fails afterwards — LiveKit connect, track
   *  publish, a worker that never joins — surfaces through the room component's own handlers,
   *  not here. */
  error: string | null;
  /** Drop the room and clear state. Safe to call when not connected. */
  disconnect: () => void;
}

export function useLiveCallConnection(
  feature: LiveCallFeature,
  sessionId: string | null,
  /** Nothing is fetched until this is true — the caller decides when a room is appropriate. */
  enabled: boolean,
  mode: LiveCallMode = "qa",
): UseLiveCallConnectionResult {
  const [connection, setConnection] = React.useState<LiveCallConnection | null>(null);
  const [connecting, setConnecting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!enabled || !sessionId) {
      setConnection(null);
      setError(null);
      return;
    }

    // The room owns the speakers from here. lib/tts.ts assumes it is the only audio source in
    // the app (module-global `currentAudio`), so a Piper clip still playing would talk straight
    // over the avatar.
    stopCurrent();

    let cancelled = false;
    setConnecting(true);
    setError(null);

    fetchLiveCallToken(feature, sessionId, mode)
      .then((result) => {
        if (!cancelled) setConnection({ token: result.token, url: result.url });
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't start the call.");
        }
      })
      .finally(() => {
        if (!cancelled) setConnecting(false);
      });

    return () => {
      cancelled = true;
    };
  }, [enabled, feature, sessionId, mode]);

  const disconnect = React.useCallback(() => {
    setConnection(null);
    setError(null);
  }, []);

  return { connection, connecting, error, disconnect };
}
