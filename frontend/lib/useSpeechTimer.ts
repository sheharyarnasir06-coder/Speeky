"use client";

import * as React from "react";

/** Display refresh only — elapsed time is computed from timestamps, never accumulated a tick
 *  at a time, so a throttled background tab cannot make the clock run slow. */
const TICK_MS = 250;

export interface UseSpeechTimerOptions {
  /** Hard limit in seconds, or null for an untimed session (the clock still counts up). */
  limitSeconds: number | null;
  /** Whether the clock should be advancing right now. Public Speaking passes `isVoiceActive`,
   *  so the timer starts, freezes and resumes with the recording socket itself. */
  running: boolean;
  /** Fired once, on the first tick at or past the limit. Never fires when limitSeconds is null. */
  onExpire?: () => void;
}

export interface UseSpeechTimerResult {
  elapsedSeconds: number;
  /** Seconds left, floored at 0. Null when there is no limit. */
  remainingSeconds: number | null;
  hasExpired: boolean;
  reset: () => void;
}

/**
 * A stopwatch that pauses and resumes with an external boolean, plus an optional hard limit.
 *
 * Time is banked in whole segments: on the falling edge of `running` the live segment is added
 * to `elapsedRef`, and on the rising edge a fresh start timestamp is taken. Pause time therefore
 * costs nothing, and no drift accumulates across many pauses the way `elapsed += TICK` would.
 */
export function useSpeechTimer({
  limitSeconds,
  running,
  onExpire,
}: UseSpeechTimerOptions): UseSpeechTimerResult {
  const [elapsedSeconds, setElapsedSeconds] = React.useState(0);
  const [hasExpired, setHasExpired] = React.useState(false);

  /** Seconds banked from completed run segments. */
  const bankedRef = React.useRef(0);
  /** performance.now() at the start of the live segment, or null while paused. */
  const startedAtRef = React.useRef<number | null>(null);
  /** Latch: onExpire is a one-shot, and it fires from an interval that keeps running until the
   *  caller reacts to it. */
  const firedRef = React.useRef(false);
  const onExpireRef = React.useRef(onExpire);
  onExpireRef.current = onExpire;

  const read = React.useCallback(() => {
    const live = startedAtRef.current === null ? 0 : (performance.now() - startedAtRef.current) / 1000;
    return bankedRef.current + live;
  }, []);

  React.useEffect(() => {
    if (!running) {
      // Falling edge: bank the segment that just ended and settle the display on its real value,
      // so a paused clock shows the time actually spent rather than the last 250ms sample.
      if (startedAtRef.current !== null) {
        bankedRef.current += (performance.now() - startedAtRef.current) / 1000;
        startedAtRef.current = null;
        setElapsedSeconds(bankedRef.current);
      }
      return;
    }

    startedAtRef.current = performance.now();

    const tick = () => {
      const elapsed = read();
      setElapsedSeconds(elapsed);
      if (limitSeconds !== null && !firedRef.current && elapsed >= limitSeconds) {
        firedRef.current = true;
        setHasExpired(true);
        onExpireRef.current?.();
      }
    };

    tick();
    const interval = setInterval(tick, TICK_MS);
    return () => clearInterval(interval);
  }, [running, limitSeconds, read]);

  const reset = React.useCallback(() => {
    bankedRef.current = 0;
    startedAtRef.current = running ? performance.now() : null;
    firedRef.current = false;
    setElapsedSeconds(0);
    setHasExpired(false);
  }, [running]);

  return {
    elapsedSeconds,
    remainingSeconds: limitSeconds === null ? null : Math.max(0, limitSeconds - elapsedSeconds),
    hasExpired,
    reset,
  };
}

/** mm:ss, for both the countdown and the untimed elapsed readout. */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}
