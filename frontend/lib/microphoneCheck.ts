export type MicrophonePermissionState = "granted" | "denied" | "prompt" | "unknown";

export type MicrophoneCheckFailureReason =
  | "unsupported"
  | "permission_denied"
  | "no_audio"
  | "unknown";

export interface MicrophoneCheckResult {
  ok: boolean;
  reason?: MicrophoneCheckFailureReason;
  message?: string;
}

interface MicrophoneInputTestOptions {
  durationMs?: number;
  signalThreshold?: number;
}

type AudioContextConstructor = typeof AudioContext;

function getAudioContextConstructor(): AudioContextConstructor | undefined {
  return (
    window.AudioContext ||
    (window as typeof window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext
  );
}

export function isMicrophoneCheckSupported() {
  return Boolean(
    typeof window !== "undefined" &&
      typeof navigator.mediaDevices?.getUserMedia === "function" &&
      typeof window.MediaRecorder !== "undefined" &&
      getAudioContextConstructor()
  );
}

export async function getMicrophonePermissionState(): Promise<MicrophonePermissionState> {
  if (typeof navigator === "undefined" || !navigator.permissions?.query) {
    return "unknown";
  }

  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    return status.state;
  } catch {
    return "unknown";
  }
}

export async function requestAndTestMicrophoneInput({
  durationMs = 2500,
  signalThreshold = 12,
}: MicrophoneInputTestOptions = {}): Promise<MicrophoneCheckResult> {
  if (!isMicrophoneCheckSupported()) {
    return {
      ok: false,
      reason: "unsupported",
      message: "This browser does not support microphone recording for Speeky.",
    };
  }

  let stream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const AudioContextClass = getAudioContextConstructor();
    if (!AudioContextClass) {
      return {
        ok: false,
        reason: "unsupported",
        message: "This browser cannot run the microphone input test.",
      };
    }

    audioContext = new AudioContextClass();
    // The getUserMedia await above breaks the synchronous user-gesture chain, so on
    // iOS Safari and most low-end/Android browsers the new AudioContext starts (and
    // stays) "suspended" — the analyser never sees a live sample, so the loop below
    // always reads silence no matter how loud the mic input is. Desktop Chrome/Edge
    // auto-resume regardless, which is why this only ever reproduced on mobile.
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);

    const samples = new Uint8Array(analyser.fftSize);
    let strongestSignal = 0;
    const startedAt = performance.now();

    while (performance.now() - startedAt < durationMs) {
      analyser.getByteTimeDomainData(samples);

      for (const sample of samples) {
        strongestSignal = Math.max(strongestSignal, Math.abs(sample - 128));
      }

      if (strongestSignal >= signalThreshold) {
        return { ok: true };
      }

      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }

    return {
      ok: false,
      reason: "no_audio",
      message: "We can't hear you. Check your microphone, headset mute switch, or input device.",
    };
  } catch (err) {
    if (err instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(err.name)) {
      return {
        ok: false,
        reason: "permission_denied",
        message: "Microphone access is blocked.",
      };
    }

    if (err instanceof DOMException && ["NotFoundError", "DevicesNotFoundError"].includes(err.name)) {
      return {
        ok: false,
        reason: "unsupported",
        message: "No microphone was found on this device.",
      };
    }

    return {
      ok: false,
      reason: "unknown",
      message: "Could not complete the microphone check.",
    };
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
    await audioContext?.close().catch(() => undefined);
  }
}
