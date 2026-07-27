"use client";

export type VoiceReadinessStatus =
  | "ready"
  | "needs_check"
  | "permission_denied"
  | "unsupported";

const VOICE_READY_CACHE_KEY = "speeky.voiceReadiness.lastPassedAt";
const VOICE_READY_TTL_MS = 2 * 60 * 1000;
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
