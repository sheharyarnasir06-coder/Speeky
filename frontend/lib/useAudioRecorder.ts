"use client";

import * as React from "react";
import { clearVoiceReady } from "@/lib/voiceReadiness";

export type RecorderState = "idle" | "recording" | "stopping";

const CANDIDATE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return undefined;
  }
  return CANDIDATE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

/**
 * Thin MediaRecorder wrapper shared by every feature that needs a real mic-recorded
 * clip (Pronunciation Coach attempts/retries, Daily Challenge turns) — one mic
 * permission prompt flow, one place to fix browser quirks.
 */
export function useAudioRecorder() {
  const [state, setState] = React.useState<RecorderState>("idle");
  const [error, setError] = React.useState<string | null>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const streamRef = React.useRef<MediaStream | null>(null);

  const isSupported =
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";

  const start = React.useCallback(async () => {
    setError(null);
    if (!isSupported) {
      setError("Microphone recording isn't supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorderRef.current = recorder;
      recorder.start();
      setState("recording");
    } catch {
      clearVoiceReady();
      setError("Couldn't access the microphone — check your browser permissions.");
    }
  }, [isSupported]);

  const stop = React.useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const recorder = recorderRef.current;
      if (!recorder || recorder.state !== "recording") {
        resolve(null);
        return;
      }
      setState("stopping");
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setState("idle");
        resolve(blob.size > 0 ? blob : null);
      };
      recorder.stop();
    });
  }, []);

  React.useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return { state, isRecording: state === "recording", isSupported, error, start, stop };
}
