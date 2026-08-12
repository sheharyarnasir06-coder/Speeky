/**
 * Temporal filtering — the layer that turns flickering per-frame readings into events a human
 * would agree happened.
 *
 * Raw landmark output is noisy. A boolean derived directly from it ("is smiling", "is looking
 * away") chatters dozens of times a second around its threshold, which turns into wildly
 * inflated event counts: an unfiltered look-away detector reports hundreds of episodes in a
 * three-minute talk. Three mechanisms fix that, and all three are needed:
 *
 *   - **EMA** on continuous signals, to damp measurement noise.
 *   - **Schmitt trigger** (separate enter/exit thresholds) on booleans, so a value sitting
 *     exactly on the threshold does not oscillate.
 *   - **Dwell + refractory** on events, so only a state that persisted counts, and a single
 *     real event cannot be double-counted as it settles.
 *
 * One distinction runs through the whole vision layer and is easy to erase by accident:
 * **percentages are frame-weighted, events are dwell-gated.** A 300ms glance away lowers
 * `on_camera_pct` — it genuinely happened — but contributes zero to `away_episodes`, because it
 * is not what anyone means by "looking away". Both are correct answers to different questions.
 *
 * Pure and synchronous — no React, no DOM, no timers. Time is always passed in.
 */

/**
 * Exponential moving average with a **time constant**, not a fixed alpha.
 *
 * `alpha = 1 - exp(-dt/tau)` is derived from the actual gap between samples, which matters
 * because the cadence is not fixed: models run at different rates, the degradation ladder
 * changes those rates mid-session, and frames get dropped. A hard-coded alpha would smooth
 * twice as hard at half the sample rate, so the same head movement would score differently on
 * a fast and a slow laptop.
 */
export class Ema {
  private value: number | null = null;
  private lastAtMs: number | null = null;

  /** @param tauMs time constant in milliseconds — larger is smoother and laggier. */
  constructor(private readonly tauMs: number) {}

  /** Feed a sample. Returns the smoothed value. */
  push(sample: number, atMs: number): number {
    if (this.value === null || this.lastAtMs === null) {
      this.value = sample;
      this.lastAtMs = atMs;
      return sample;
    }

    const dt = atMs - this.lastAtMs;
    this.lastAtMs = atMs;

    // A large gap means the tab was hidden or detection was lost. Interpolating across it would
    // invent motion that never happened, so restart from the new sample instead.
    if (dt <= 0 || dt > this.tauMs * 20) {
      this.value = sample;
      return sample;
    }

    const alpha = 1 - Math.exp(-dt / this.tauMs);
    this.value += alpha * (sample - this.value);
    return this.value;
  }

  get current(): number | null {
    return this.value;
  }

  /** Drop all history. Called on a detection gap so stale state cannot leak across it. */
  reset(): void {
    this.value = null;
    this.lastAtMs = null;
  }
}

/**
 * Schmitt trigger: enters on one threshold, exits on a lower one.
 *
 * With a single threshold, a signal hovering at the boundary flips state on every frame. The
 * gap between `enter` and `exit` is what makes the output stable.
 */
export class SchmittTrigger {
  private active = false;

  constructor(
    private readonly enter: number,
    private readonly exit: number,
  ) {
    if (exit > enter) {
      throw new Error(`SchmittTrigger exit (${exit}) must not exceed enter (${enter})`);
    }
  }

  push(value: number): boolean {
    if (this.active) {
      if (value < this.exit) this.active = false;
    } else if (value >= this.enter) {
      this.active = true;
    }
    return this.active;
  }

  get state(): boolean {
    return this.active;
  }

  reset(): void {
    this.active = false;
  }
}

export interface EpisodeSummary {
  count: number;
  totalMs: number;
  longestMs: number;
  meanMs: number | null;
}

/**
 * Counts episodes of a boolean state, gated on minimum duration and a refractory window.
 *
 * `minDwellMs` is what separates a glance from a lapse. `refractoryMs` stops one real event
 * being counted twice while the underlying signal settles — without it a gesture that dips
 * momentarily below threshold mid-stroke registers as two gestures.
 *
 * Note that `totalMs` accumulates over **every** active span, including ones too short to
 * count as episodes. That is deliberate: it is the frame-weighted quantity that percentages
 * come from, kept separate from the dwell-gated `count`.
 */
export class EpisodeDetector {
  private activeSinceMs: number | null = null;
  private lastEpisodeEndedMs: number | null = null;

  private count = 0;
  private totalMs = 0;
  private longestMs = 0;
  private episodeTotalMs = 0;

  constructor(
    private readonly minDwellMs: number,
    private readonly refractoryMs = 0,
  ) {}

  /** Feed the (already de-noised) boolean state for this instant. */
  push(active: boolean, atMs: number): void {
    if (active) {
      if (this.activeSinceMs === null) this.activeSinceMs = atMs;
      return;
    }
    this.close(atMs);
  }

  /** Close any open span — call when the session ends or detection is lost. */
  close(atMs: number): void {
    if (this.activeSinceMs === null) return;

    const duration = atMs - this.activeSinceMs;
    this.activeSinceMs = null;
    if (duration <= 0) return;

    // Frame-weighted: every active span counts toward the total, however brief.
    this.totalMs += duration;

    if (duration < this.minDwellMs) return;

    // Dwell-gated: only sustained spans become episodes, and only outside the refractory window.
    const withinRefractory =
      this.lastEpisodeEndedMs !== null && atMs - this.lastEpisodeEndedMs < this.refractoryMs;
    if (withinRefractory) return;

    this.count += 1;
    this.episodeTotalMs += duration;
    this.longestMs = Math.max(this.longestMs, duration);
    this.lastEpisodeEndedMs = atMs;
  }

  /** Drop the open span without recording it — used when a detection gap makes its end unknown. */
  reset(): void {
    this.activeSinceMs = null;
  }

  summary(): EpisodeSummary {
    return {
      count: this.count,
      totalMs: this.totalMs,
      longestMs: this.longestMs,
      meanMs: this.count > 0 ? this.episodeTotalMs / this.count : null,
    };
  }
}

/**
 * Detects a there-and-back excursion in a signal — the shape of a nod or a head shake.
 *
 * Requires the signal to move at least `minAmplitude` away from its resting value and return,
 * inside `[minDurationMs, maxDurationMs]`. The duration window is what excludes a slow
 * postural drift, which crosses the same amplitude but over several seconds.
 *
 * Callers must additionally check that the excursion happened on the *intended* axis — a lean
 * moves pitch and roll together, and only the axis check distinguishes it from a nod. See
 * `dominantAxis`.
 */
export class ExcursionDetector {
  private baseline: number | null = null;
  private peak = 0;
  private startedAtMs: number | null = null;
  private lastEventEndedMs: number | null = null;
  private count = 0;

  constructor(
    private readonly minAmplitude: number,
    private readonly minDurationMs: number,
    private readonly maxDurationMs: number,
    private readonly refractoryMs = 0,
  ) {}

  push(value: number, atMs: number): boolean {
    if (this.baseline === null) {
      this.baseline = value;
      return false;
    }

    const deviation = value - this.baseline;
    const magnitude = Math.abs(deviation);

    if (this.startedAtMs === null) {
      if (magnitude >= this.minAmplitude) {
        this.startedAtMs = atMs;
        this.peak = magnitude;
      } else {
        // Track the resting value slowly, so a gradual posture change becomes the new baseline
        // rather than reading as a permanent excursion.
        this.baseline += deviation * 0.02;
      }
      return false;
    }

    this.peak = Math.max(this.peak, magnitude);

    // Returned to rest: the excursion is complete.
    if (magnitude < this.minAmplitude * 0.4) {
      const duration = atMs - this.startedAtMs;
      this.startedAtMs = null;

      const withinRefractory =
        this.lastEventEndedMs !== null && atMs - this.lastEventEndedMs < this.refractoryMs;
      if (
        !withinRefractory &&
        duration >= this.minDurationMs &&
        duration <= this.maxDurationMs
      ) {
        this.count += 1;
        this.lastEventEndedMs = atMs;
        return true;
      }
      return false;
    }

    // Held too long to be an excursion — treat the held position as the new resting value.
    if (atMs - this.startedAtMs > this.maxDurationMs) {
      this.startedAtMs = null;
      this.baseline = value;
    }
    return false;
  }

  get total(): number {
    return this.count;
  }

  reset(): void {
    this.startedAtMs = null;
    this.baseline = null;
  }
}

/**
 * Which of three axes moved most.
 *
 * Used to reject a lean being counted as a nod: both move pitch, but a lean moves roll or yaw
 * at least as much, while a genuine nod is pitch-dominant.
 */
export function dominantAxis(
  deltas: { yaw: number; pitch: number; roll: number },
): "yaw" | "pitch" | "roll" {
  const { yaw, pitch, roll } = {
    yaw: Math.abs(deltas.yaw),
    pitch: Math.abs(deltas.pitch),
    roll: Math.abs(deltas.roll),
  };
  if (pitch >= yaw && pitch >= roll) return "pitch";
  return yaw >= roll ? "yaw" : "roll";
}
