"use client";

/**
 * A plain self-view camera: getUserMedia, an element to attach it to, and a stop on the way out.
 *
 * Deliberately unrelated to lib/vision/useVideoAnalysis — that one loads MediaPipe and feeds the
 * delivery scorer. This is for phases where the user should see themselves but nothing is being
 * measured (Public Speaking's Q&A), so it carries none of that cost and its frames go nowhere.
 */

import * as React from "react";

export interface UseSelfCameraResult {
  /**
   * A callback ref, not a RefObject, and that is the whole point.
   *
   * The consumer's <video> can mount long after getUserMedia resolves — Public Speaking's Q&A
   * renders it inside a dynamically-imported modal that first shows a connecting spinner, so the
   * element does not exist for hundreds of milliseconds after the camera opens. The old
   * RefObject version read `videoRef.current` once, found null, and silently gave up: the stream
   * stayed live (camera light on) with nothing displaying it.
   *
   * A callback ref is notified when the element actually arrives, so attachment works in either
   * order.
   */
  videoRef: (node: HTMLVideoElement | null) => void;
  error: string | null;
}

export function useSelfCamera(enabled: boolean): UseSelfCameraResult {
  const [error, setError] = React.useState<string | null>(null);
  const nodeRef = React.useRef<HTMLVideoElement | null>(null);
  const streamRef = React.useRef<MediaStream | null>(null);

  /** Idempotent: runs whenever either half (element, stream) becomes available. */
  const attach = React.useCallback(() => {
    const video = nodeRef.current;
    const stream = streamRef.current;
    if (!video || !stream || video.srcObject === stream) return;
    video.srcObject = stream;
    void video.play();
  }, []);

  const videoRef = React.useCallback(
    (node: HTMLVideoElement | null) => {
      nodeRef.current = node;
      if (node) attach();
    },
    [attach],
  );

  React.useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    // Undefined rather than a rejected promise when the page is not on localhost or HTTPS —
    // a bare `.getUserMedia` call would throw a TypeError that reads like a bug in this hook.
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Camera needs a secure page (localhost or HTTPS).");
      return;
    }

    setError(null);
    navigator.mediaDevices
      .getUserMedia({ video: true, audio: false })
      .then((result) => {
        // The room is what owns the microphone; a second audio capture here would double it.
        if (cancelled) {
          result.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = result;
        attach();
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? `Camera unavailable: ${err.message}` : "Camera unavailable");
        }
      });

    return () => {
      cancelled = true;
      // A camera indicator left on after the panel closes reads as a privacy breach, so release
      // the device rather than just detaching the element.
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (nodeRef.current) nodeRef.current.srcObject = null;
    };
  }, [enabled, attach]);

  return { videoRef, error };
}
