import * as React from "react";
import { pingPracticeTime, type Milestone, type PracticeSessionType } from "./practiceTime";

const PING_INTERVAL_MS = 60_000;

/** PDG-US-15: fires a heartbeat ping every 60s while `active` is true, crediting
 * lifetime practice time server-side. Ticks immediately on activation too, so a
 * session shorter than one interval still registers as the primary session.
 * Returns any milestone(s) unlocked by the latest ping, for a celebration UI. */
export function usePracticeTimePing(
  sessionType: PracticeSessionType,
  sessionId: string | null,
  active: boolean,
) {
  const [newlyUnlocked, setNewlyUnlocked] = React.useState<Milestone[]>([]);

  React.useEffect(() => {
    if (!active || !sessionId) return;
    const activeSessionId = sessionId;

    let cancelled = false;
    function tick() {
      pingPracticeTime(sessionType, activeSessionId)
        .then((result) => {
          if (!cancelled && result.newly_unlocked.length > 0) {
            setNewlyUnlocked((prev) => [...prev, ...result.newly_unlocked]);
          }
        })
        .catch(() => {
          // Non-critical — a missed ping just means that slice of time isn't credited.
        });
    }

    tick();
    const interval = setInterval(tick, PING_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionType, sessionId, active]);

  function dismissMilestone(hours: number) {
    setNewlyUnlocked((prev) => prev.filter((m) => m.hours !== hours));
  }

  return { newlyUnlocked, dismissMilestone };
}
