"use client";

/**
 * Drives inference off the video element's decoded frames.
 *
 * Models run at staggered cadences and the ladder demotes them when the device cannot keep up.
 * Adding a model is a new entry in `TIERS`, not a rewrite.
 *
 * Two rules that are easy to get wrong and expensive to debug:
 *
 * 1. **At most ONE model runs per frame callback.** Face, pose and hands cost roughly 8-20ms
 *    each on single-thread SIMD; stacking all three onto one frame blows a 33ms budget
 *    immediately. Staggering them is what makes this viable without threads.
 * 2. **Timestamps must strictly increase per landmarker instance**, not globally. Because the
 *    models run at different cadences they each see a different subsequence of frames, so a
 *    single shared counter can hand one landmarker a timestamp it has already seen. MediaPipe
 *    treats that as a fatal wasm abort, not a recoverable error.
 *
 * The loop prefers `requestVideoFrameCallback`, which fires exactly once per decoded frame — so
 * inference never runs twice on the same image. Firefox lacks it, hence the rAF fallback with a
 * `currentTime` guard that does the same job less precisely.
 */

export type ModelKind = "face" | "pose" | "hand";

export type DegradationTier = "high" | "medium" | "low" | "minimal";

/**
 * The ladder.
 *
 * Cadences are chosen from what each signal actually needs: blinks last 100-400ms so face wants
 * the highest rate; posture and sway are slow, so pose at 6Hz cuts the most expensive model 5x;
 * gesture strokes last 300ms-2s, so hands at 8Hz resolves onset and offset to +/-125ms.
 *
 * Hands are switched off before pose because gesture *count, rate, amplitude and symmetry* all
 * survive on pose wrists alone — only finger-level detail is lost. Dropping pose instead would
 * take posture with it, which has no fallback at all.
 */
export const TIERS: Record<
  DegradationTier,
  { width: number; height: number; cadences: Partial<Record<ModelKind, number>> }
> = {
  high: { width: 640, height: 480, cadences: { face: 15, pose: 6, hand: 8 } },
  medium: { width: 480, height: 360, cadences: { face: 10, pose: 4, hand: 5 } },
  low: { width: 320, height: 240, cadences: { face: 6, pose: 3 } },
  minimal: { width: 320, height: 240, cadences: { face: 5 } },
};

const TIER_ORDER: DegradationTier[] = ["high", "medium", "low", "minimal"];

/** Demote when a single inference costs more than this on average — roughly 1.5 frames at 30fps. */
const DEMOTE_COST_MS = 45;
/** ...or when the achieved analysis rate falls this far below target. */
const DEMOTE_RATE_RATIO = 0.6;
/** Either condition must persist this long, so one janky second does not demote. */
const DEMOTE_DWELL_MS = 5000;
/** Headroom must last this long before the single allowed promotion. */
const PROMOTE_DWELL_MS = 30_000;
/** Below this achieved rate at the bottom tier, analysis is not viable at all. */
const FLOOR_HZ = 4;
const FLOOR_DWELL_MS = 10_000;

export interface FrameSchedulerOptions {
  video: HTMLVideoElement;
  /** Explicit cadences, overriding the tier table. Used by tests and by single-model callers. */
  cadences?: Partial<Record<ModelKind, number>>;
  /** Starting tier. Ignored when `cadences` is given. */
  tier?: DegradationTier;
  /** Which models the caller actually loaded. A tier never schedules a model not listed here. */
  available?: ModelKind[];
  /** The capture track, for resolution changes. Omit to keep the cadence-only ladder. */
  track?: MediaStreamTrack | null;
  /** Run one inference. Must be synchronous — it is inside the frame callback. */
  onInference: (kind: ModelKind, timestampMs: number) => void;
  /** Reports measured cost, for callers that want their own telemetry. */
  onSample?: (kind: ModelKind, durationMs: number) => void;
  onTierChange?: (tier: DegradationTier) => void;
  /** Fired when even the bottom tier cannot hold — the caller should stop analysis and report
   *  insufficient_data rather than submitting numbers from a device that never kept up. */
  onUnviable?: () => void;
}

/**
 * lib.dom declares requestVideoFrameCallback as always present, but Firefox does not implement
 * it — so the feature test below is a runtime necessity even though TypeScript thinks it is
 * redundant. This partial view is what lets us test for it without fighting the DOM lib.
 */
type VideoFrameCallbackHost = {
  requestVideoFrameCallback?: (callback: (now: number) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export interface SchedulerStats {
  tier: DegradationTier;
  tierChanges: number;
  framesSeen: number;
  framesAnalyzed: number;
  /** Per-model successful inference counts, for the coverage denominators. */
  attempts: Record<ModelKind, number>;
  /** Mean inference cost per model, in ms. */
  meanCostMs: Record<ModelKind, number | null>;
  /** Seconds the loop was actually running — excludes time with the tab hidden, which is what
   *  `video_features.duration_seconds` reports. */
  activeSeconds: number;
}

export interface FrameScheduler {
  start(): void;
  stop(): void;
  stats(): SchedulerStats;
}

const MODEL_ORDER: ModelKind[] = ["face", "pose", "hand"];

export function createFrameScheduler(options: FrameSchedulerOptions): FrameScheduler {
  const { video, onInference, onSample, onTierChange, onUnviable, track } = options;
  const host = video as unknown as VideoFrameCallbackHost;
  const useVideoFrameCallback = typeof host.requestVideoFrameCallback === "function";

  // An explicit cadence map pins the scheduler and disables the ladder — a caller that has
  // asked for exact rates should not have them changed underneath it.
  const fixedCadences = options.cadences ?? null;
  const available = options.available ?? MODEL_ORDER;

  let tier: DegradationTier = options.tier ?? "high";
  let tierChanges = 0;
  let promotionsLeft = 1; // one promotion, then latch — see below
  let cadences: Partial<Record<ModelKind, number>> = fixedCadences ?? tierCadences(tier);
  let enabled = enabledFrom(cadences);

  function tierCadences(next: DegradationTier): Partial<Record<ModelKind, number>> {
    const out: Partial<Record<ModelKind, number>> = {};
    for (const [kind, hz] of Object.entries(TIERS[next].cadences) as [ModelKind, number][]) {
      // Never schedule a model the caller did not load.
      if (available.includes(kind)) out[kind] = hz;
    }
    return out;
  }

  function enabledFrom(map: Partial<Record<ModelKind, number>>): ModelKind[] {
    return MODEL_ORDER.filter((kind) => (map[kind] ?? 0) > 0);
  }

  let running = false;
  let handle: number | null = null;

  let framesSeen = 0;
  let framesAnalyzed = 0;
  let activeMs = 0;
  let lastTickAt: number | null = null;
  let lastVideoTime = -1;

  const attempts: Record<ModelKind, number> = { face: 0, pose: 0, hand: 0 };
  const costTotals: Record<ModelKind, number> = { face: 0, pose: 0, hand: 0 };
  // When each model is next due, in performance.now() terms.
  const nextDueAt: Record<ModelKind, number> = { face: 0, pose: 0, hand: 0 };
  // Per-instance monotonic timestamps. See rule 2 above.
  const lastTimestamp: Record<ModelKind, number> = { face: -1, pose: -1, hand: -1 };
  // Round-robin cursor, so a model that is perpetually due doesn't starve the others.
  let cursor = 0;

  // ── Ladder state ────────────────────────────────────────────────────────
  // Cost is an EMA rather than a running mean so the ladder reacts to the device getting hot
  // or another tab stealing the CPU, instead of being anchored by an easy first ten seconds.
  let costEma: number | null = null;
  let strainSinceMs: number | null = null;
  let healthySinceMs: number | null = null;
  let floorStrainSinceMs: number | null = null;
  let windowStartMs: number | null = null;
  let windowAnalyzed = 0;

  function targetHz(): number {
    return Object.values(cadences).reduce((sum, hz) => sum + (hz ?? 0), 0);
  }

  function applyTier(next: DegradationTier, now: number) {
    if (next === tier) return;
    tier = next;
    tierChanges += 1;
    cadences = tierCadences(tier);
    enabled = enabledFrom(cadences);
    cursor = 0;
    strainSinceMs = null;
    healthySinceMs = null;
    windowStartMs = now;
    windowAnalyzed = 0;

    // Resolution changes go through the existing track: a fresh getUserMedia would flash the
    // camera indicator and drop frames mid-session.
    if (track) {
      const { width, height } = TIERS[tier];
      void track.applyConstraints({ width: { ideal: width }, height: { ideal: height } })
        .catch(() => {
          // A device that refuses the constraint still benefits from the cadence change.
        });
    }

    onTierChange?.(tier);
  }

  /** Called once per second's worth of frames. Owns every promote/demote decision. */
  function evaluateLoad(now: number) {
    if (fixedCadences) return;
    if (windowStartMs === null) {
      windowStartMs = now;
      return;
    }

    const elapsed = now - windowStartMs;
    if (elapsed < 1000) return;

    const achievedHz = (windowAnalyzed / elapsed) * 1000;
    windowStartMs = now;
    windowAnalyzed = 0;

    const target = targetHz();
    const rateShortfall = target > 0 && achievedHz < target * DEMOTE_RATE_RATIO;
    const tooExpensive = costEma !== null && costEma > DEMOTE_COST_MS;
    const index = TIER_ORDER.indexOf(tier);

    if (rateShortfall || tooExpensive) {
      healthySinceMs = null;
      if (strainSinceMs === null) strainSinceMs = now;

      if (now - strainSinceMs >= DEMOTE_DWELL_MS && index < TIER_ORDER.length - 1) {
        applyTier(TIER_ORDER[index + 1], now);
        return;
      }

      // Already at the bottom and still failing: analysis is not viable on this device, and
      // saying so is better than submitting numbers built from a handful of frames.
      if (index === TIER_ORDER.length - 1 && achievedHz < FLOOR_HZ) {
        if (floorStrainSinceMs === null) floorStrainSinceMs = now;
        if (now - floorStrainSinceMs >= FLOOR_DWELL_MS) onUnviable?.();
      }
      return;
    }

    strainSinceMs = null;
    floorStrainSinceMs = null;

    // Promotion is allowed exactly once. Without the latch a device sitting near the boundary
    // oscillates between tiers, and every change costs a resolution renegotiation plus a
    // discontinuity in the very metrics being measured.
    if (promotionsLeft > 0 && index > 0) {
      if (healthySinceMs === null) healthySinceMs = now;
      if (now - healthySinceMs >= PROMOTE_DWELL_MS) {
        promotionsLeft -= 1;
        applyTier(TIER_ORDER[index - 1], now);
      }
    }
  }

  function pickDueModel(now: number): ModelKind | null {
    for (let step = 0; step < enabled.length; step += 1) {
      const kind = enabled[(cursor + step) % enabled.length];
      if (now >= nextDueAt[kind]) {
        cursor = (cursor + step + 1) % enabled.length;
        return kind;
      }
    }
    return null;
  }

  function tick(now: number) {
    if (!running) return;

    // Accumulate active time from tick deltas rather than wall clock. A large gap means the tab
    // was hidden; count it as a pause, not as analysed time.
    if (lastTickAt !== null) {
      const delta = now - lastTickAt;
      if (delta < 1000) activeMs += delta;
    }
    lastTickAt = now;

    // On the rAF path the same decoded frame can be seen repeatedly; only count new ones.
    const isNewFrame = useVideoFrameCallback || video.currentTime !== lastVideoTime;
    lastVideoTime = video.currentTime;

    if (isNewFrame && video.readyState >= 2 && video.videoWidth > 0) {
      framesSeen += 1;

      const kind = pickDueModel(now);
      if (kind) {
        const cadence = cadences[kind] ?? 0;
        nextDueAt[kind] = now + 1000 / cadence;

        // Strictly increasing, per landmarker. `now` can repeat across two callbacks in the
        // same millisecond, so nudge forward rather than reuse.
        const timestamp = Math.max(Math.round(now), lastTimestamp[kind] + 1);
        lastTimestamp[kind] = timestamp;

        const startedAt = performance.now();
        try {
          onInference(kind, timestamp);
          attempts[kind] += 1;
          framesAnalyzed += 1;
        } catch (error) {
          // One bad frame must not kill the session; the coverage numbers will show it.
          console.warn(`[vision] ${kind} inference failed`, error);
        }
        const cost = performance.now() - startedAt;
        costTotals[kind] += cost;
        windowAnalyzed += 1;
        // tau ~2s at typical cadences: fast enough to catch thermal throttling, slow enough to
        // ignore a single expensive frame.
        costEma = costEma === null ? cost : costEma + 0.1 * (cost - costEma);
        onSample?.(kind, cost);
      }

      evaluateLoad(now);
    }

    schedule();
  }

  function schedule() {
    if (!running) return;
    handle = useVideoFrameCallback
      ? host.requestVideoFrameCallback!((now) => tick(now))
      : requestAnimationFrame((now) => tick(now));
  }

  function cancel() {
    if (handle === null) return;
    if (useVideoFrameCallback) host.cancelVideoFrameCallback?.(handle);
    else cancelAnimationFrame(handle);
    handle = null;
  }

  function onVisibilityChange() {
    // Browsers throttle both callbacks in a hidden tab anyway; stopping explicitly keeps
    // activeSeconds honest and avoids a burst of stale frames on return.
    if (document.hidden) {
      cancel();
      lastTickAt = null;
    } else if (running && handle === null) {
      schedule();
    }
  }

  return {
    start() {
      if (running) return;
      running = true;
      lastTickAt = null;
      document.addEventListener("visibilitychange", onVisibilityChange);
      schedule();
    },

    stop() {
      running = false;
      cancel();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    },

    stats(): SchedulerStats {
      const meanCostMs = { face: null, pose: null, hand: null } as Record<ModelKind, number | null>;
      for (const kind of MODEL_ORDER) {
        meanCostMs[kind] = attempts[kind] > 0 ? costTotals[kind] / attempts[kind] : null;
      }
      return {
        tier,
        tierChanges,
        framesSeen,
        framesAnalyzed,
        attempts: { ...attempts },
        meanCostMs,
        activeSeconds: activeMs / 1000,
      };
    },
  };
}
