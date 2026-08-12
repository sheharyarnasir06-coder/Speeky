"use client";

export type VoiceReadinessStatus =
  | "ready"
  | "needs_check"
  | "permission_denied"
  | "unsupported";

const VOICE_READY_CACHE_KEY = "speeky.voiceReadiness.lastPassedAt";
// Once-per-session, not once-per-click: valid for hours so it survives a whole practice session. Re-checks still happen sooner via clearVoiceReady() when
// permission is revoked, the input device changes, or a real session's mic fails.
const VOICE_READY_TTL_MS = 1 * 60 * 60 * 1000;
const VOICE_READY_EVENT = "speeky:voice-readiness-changed";

function dispatchVoiceReadinessChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(VOICE_READY_EVENT));
}

export function getVoiceReadinessEventName() {
  return VOICE_READY_EVENT;
}

export function getLastVoiceReadyAt() {
  if (typeof window === "undefined") return null;

  const value = window.localStorage.getItem(VOICE_READY_CACHE_KEY);
  if (!value) return null;

  const timestamp = Number(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function markVoiceReady() {
  if (typeof window === "undefined") return;

  window.localStorage.setItem(VOICE_READY_CACHE_KEY, String(Date.now()));
  dispatchVoiceReadinessChanged();
}

export function clearVoiceReady() {
  if (typeof window === "undefined") return;

  const hadCachedStatus = window.localStorage.getItem(VOICE_READY_CACHE_KEY) !== null;
  window.localStorage.removeItem(VOICE_READY_CACHE_KEY);

  if (hadCachedStatus) {
    dispatchVoiceReadinessChanged();
  }
}

export function isVoiceReadyCacheFresh() {
  const lastReadyAt = getLastVoiceReadyAt();
  return lastReadyAt !== null && Date.now() - lastReadyAt < VOICE_READY_TTL_MS;
}

export async function hasRecentWorkingMicCheck() {
  if (!isVoiceReadyCacheFresh()) return false;

  if (typeof navigator === "undefined") return false;

  try {
    const permission = await navigator.permissions?.query?.({
      name: "microphone" as PermissionName,
    });

    if (permission?.state === "denied") {
      clearVoiceReady();
      return false;
    }
  } catch {
    // Safari/older browsers can throw here. Keep the recent successful input test.
  }

  return true;
}

export async function getVoiceReadinessStatus(): Promise<VoiceReadinessStatus> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    clearVoiceReady();
    return "unsupported";
  }

  try {
    const permission = await navigator.permissions?.query?.({
      name: "microphone" as PermissionName,
    });

    if (permission?.state === "denied") {
      clearVoiceReady();
      return "permission_denied";
    }
  } catch {
    // Permission query is not universally supported.
  }

  return isVoiceReadyCacheFresh() ? "ready" : "needs_check";
}

// Switching input device (headset unplugged, Bluetooth mic connected, etc.) can silently
// break a check that passed on the old device — force a recheck rather than trust a stale pass.
if (typeof navigator !== "undefined" && navigator.mediaDevices?.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", clearVoiceReady);
}
