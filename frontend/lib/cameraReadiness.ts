"use client";

/**
 * Camera readiness cache — the camera counterpart to lib/voiceReadiness.ts.
 *
 * Two things differ from the voice version, both deliberate:
 *
 * 1. **A much longer TTL (30 minutes, versus voice's 2).** The microphone check is a two-second
 *    "say a word". The camera check is permission, then framing, then two 3-second calibration
 *    holds — roughly 20 seconds of the user's attention and concentration. Re-running that
 *    every couple of minutes would be genuinely irritating, and the thing it verifies (a camera
 *    exists and works) does not change on a two-minute cadence.
 *
 * 2. **The calibration itself is persisted**, not just a "you passed" flag. Re-deriving where
 *    the user's lens is relative to their neutral head pose is the expensive part; as long as
 *    they have not moved to a different machine or resolution, it stays valid.
 */

import type { GazeCalibration } from "./vision/gaze";

export type CameraReadinessStatus = "ready" | "needs_check" | "permission_denied" | "unsupported";

const CAMERA_READY_CACHE_KEY = "speeky.cameraReadiness.lastPassedAt";
const CAMERA_CALIBRATION_KEY = "speeky.cameraCalibration.v1";
const CAMERA_READY_EVENT = "speeky:camera-readiness-changed";

/** See the module docstring for why this is 30 minutes rather than voice's 2. */
const CAMERA_READY_TTL_MS = 30 * 60 * 1000;

/** A calibration older than this is discarded even on the same machine — people move rooms,
 *  change chairs, and re-mount laptops, all of which invalidate the lens geometry. */
const CALIBRATION_TTL_MS = 24 * 60 * 60 * 1000;

interface StoredCalibration {
  calibration: GazeCalibration;
  /** Capture dimensions at the time of fitting. A different resolution means a different field
   *  of view, which means the angles no longer correspond. */
  videoWidth: number;
  videoHeight: number;
  savedAt: number;
}

function dispatchCameraReadinessChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(CAMERA_READY_EVENT));
}

export function getCameraReadinessEventName() {
  return CAMERA_READY_EVENT;
}

export function getLastCameraReadyAt(): number | null {
  if (typeof window === "undefined") return null;

  const value = window.localStorage.getItem(CAMERA_READY_CACHE_KEY);
  if (!value) return null;

  const timestamp = Number(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function markCameraReady() {
  if (typeof window === "undefined") return;

  window.localStorage.setItem(CAMERA_READY_CACHE_KEY, String(Date.now()));
  dispatchCameraReadinessChanged();
}

export function clearCameraReady() {
  if (typeof window === "undefined") return;

  const hadCachedStatus = window.localStorage.getItem(CAMERA_READY_CACHE_KEY) !== null;
  window.localStorage.removeItem(CAMERA_READY_CACHE_KEY);

  if (hadCachedStatus) dispatchCameraReadinessChanged();
}

export function isCameraReadyCacheFresh(): boolean {
  const lastReadyAt = getLastCameraReadyAt();
  return lastReadyAt !== null && Date.now() - lastReadyAt < CAMERA_READY_TTL_MS;
}

/** Persist a fitted calibration alongside the capture dimensions it was fitted at. */
export function saveCalibration(
  calibration: GazeCalibration,
  videoWidth: number,
  videoHeight: number,
) {
  if (typeof window === "undefined") return;

  const stored: StoredCalibration = { calibration, videoWidth, videoHeight, savedAt: Date.now() };
  try {
    window.localStorage.setItem(CAMERA_CALIBRATION_KEY, JSON.stringify(stored));
  } catch {
    // A full or disabled localStorage is not worth failing a session over — the user simply
    // recalibrates next time.
  }
}

/**
 * Load a stored calibration, if one is still applicable.
 *
 * Returns null rather than a stale calibration whenever the geometry may have changed. A wrong
 * calibration is worse than none: it produces confident numbers built on the wrong baseline,
 * whereas no calibration at least flags itself and gets discounted downstream.
 */
export function loadCalibration(
  videoWidth?: number,
  videoHeight?: number,
): GazeCalibration | null {
  if (typeof window === "undefined") return null;

  const raw = window.localStorage.getItem(CAMERA_CALIBRATION_KEY);
  if (!raw) return null;

  try {
    const stored = JSON.parse(raw) as StoredCalibration;
    if (!stored?.calibration || typeof stored.savedAt !== "number") return null;

    if (Date.now() - stored.savedAt > CALIBRATION_TTL_MS) return null;

    // Different capture size => different field of view => the angles no longer correspond.
    if (
      videoWidth !== undefined &&
      videoHeight !== undefined &&
      (stored.videoWidth !== videoWidth || stored.videoHeight !== videoHeight)
    ) {
      return null;
    }

    return stored.calibration;
  } catch {
    return null;
  }
}

export function clearCalibration() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(CAMERA_CALIBRATION_KEY);
}

/**
 * Whether the camera check can be skipped for this session.
 *
 * Requires both a fresh pass and a still-valid calibration: passing the device check without a
 * calibration would let a session run uncalibrated while the UI implied it was ready.
 */
export async function hasRecentWorkingCameraCheck(): Promise<boolean> {
  if (!isCameraReadyCacheFresh()) return false;
  if (loadCalibration() === null) return false;
  if (typeof navigator === "undefined") return false;

  try {
    const permission = await navigator.permissions?.query?.({
      name: "camera" as PermissionName,
    });

    if (permission?.state === "denied") {
      clearCameraReady();
      return false;
    }
  } catch {
    // Safari and older browsers throw on an unknown permission name. Keep the recent pass.
  }

  return true;
}

export async function getCameraReadinessStatus(): Promise<CameraReadinessStatus> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    clearCameraReady();
    return "unsupported";
  }

  try {
    const permission = await navigator.permissions?.query?.({
      name: "camera" as PermissionName,
    });

    if (permission?.state === "denied") {
      clearCameraReady();
      return "permission_denied";
    }
  } catch {
    // Permission query is not universally supported.
  }

  return isCameraReadyCacheFresh() ? "ready" : "needs_check";
}
