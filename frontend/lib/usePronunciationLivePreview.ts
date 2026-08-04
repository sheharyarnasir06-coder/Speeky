"use client";

import * as React from "react";

const SAMPLE_RATE = 16000; // must match backend/lib/voice_ws.py's SAMPLE_RATE

// Same normalization rule backend/lib/text_alignment.py's normalize() uses (lowercase,
// strip everything but letters/apostrophe) — keeps the live preview's word-matching in
// step with the authoritative classifier's, even though this is a much simpler exact
// compare (no fuzzy/near-match ratio, no stress detection — those need the full
// upload-based analysis, this is just a cheap live hint).
function normalizeWord(word: string): string {
  return word.toLowerCase().replace(/[^a-z']/g, "");
}

export type WordPreviewStatus = "pending" | "correct" | "wrong";

// Plain positional compare (target[i] vs recognized[i]) breaks the moment a word is
// skipped or STT drops/adds one.
// This is a small Levenshtein alignment instead — a target word only gets a verdict when it's actually matched
// (correct) or substituted (wrong) against a recognized word; a target word the
// alignment drops entirely (skipped, or not reached yet) stays "pending" rather than
// being forced red or green.
function alignWords(target: string[], recognized: string[]): WordPreviewStatus[] {
  const n = target.length;
  const m = recognized.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 0; i <= n; i++) dp[i][0] = i;
  for (let j = 0; j <= m; j++) dp[0][j] = j;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const cost = target[i - 1] === recognized[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1, // drop target[i-1] (skipped)
        dp[i][j - 1] + 1, // extra recognized[j-1] (filler/stutter, ignored)
        dp[i - 1][j - 1] + cost, // match or substitute
      );
    }
  }

  const statuses: WordPreviewStatus[] = new Array(n).fill("pending");
  let i = n;
  let j = m;
  while (i > 0 && j > 0) {
    const cost = target[i - 1] === recognized[j - 1] ? 0 : 1;
    if (dp[i][j] === dp[i - 1][j - 1] + cost) {
      statuses[i - 1] = cost === 0 ? "correct" : "wrong";
      i--;
      j--;
    } else if (dp[i][j] === dp[i - 1][j] + 1) {
      i--; // skipped target word — leave "pending"
    } else {
      j--; // extra recognized word — doesn't touch any target word
    }
  }
  return statuses;
}

/**
 * Live word-by-word preview while reading a known target sentence/passage aloud.
 * Opens its own lightweight WebSocket to backend/lib/voice_ws.py's LivePreviewSession
 * (no VAD — just periodic partial transcripts streaming from the very start of the
 * recording) and does a simple positional normalized-word compare against `targetWords`, entirely
 * client-side. Purely cosmetic: the authoritative per-word result still comes from the
 * caller's own existing upload-based scoring (submitAttempt / submitPassageAssessment)
 * — this hook never touches that, and any failure here is swallowed rather than
 * surfaced, since losing the preview must never block the real recording.
 */
export function usePronunciationLivePreview(targetWords: string[], getWsUrl: () => string | null) {
  const [wordStatuses, setWordStatuses] = React.useState<WordPreviewStatus[]>(() =>
    targetWords.map(() => "pending"),
  );
  const socketRef = React.useRef<WebSocket | null>(null);
  const audioContextRef = React.useRef<AudioContext | null>(null);
  const workletNodeRef = React.useRef<AudioWorkletNode | null>(null);
  const micStreamRef = React.useRef<MediaStream | null>(null);
  // start()/onmessage read the *current* target words without needing to be
  // recreated every time the caller's target sentence changes.
  const targetWordsRef = React.useRef(targetWords);
  targetWordsRef.current = targetWords;
  // Previous tick's raw (unsmoothed) alignment — see onmessage below.
  const lastRawRef = React.useRef<WordPreviewStatus[]>(targetWords.map(() => "pending"));

  const reset = React.useCallback(() => {
    const initial = targetWordsRef.current.map(() => "pending" as WordPreviewStatus);
    setWordStatuses(initial);
    lastRawRef.current = initial;
  }, []);

  const teardown = React.useCallback(() => {
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      void audioContextRef.current.close();
    }
    audioContextRef.current = null;
    socketRef.current?.close(1000);
    socketRef.current = null;
  }, []);

  const start = React.useCallback(async () => {
    if (socketRef.current) return;
    const wsUrl = getWsUrl();
    if (!wsUrl) return;
    reset();

    try {
      const socket = new WebSocket(wsUrl);
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string);
          if (data.type !== "partial" || typeof data.text !== "string") return;
          const recognized: string[] = data.text.split(/\s+/).filter(Boolean).map(normalizeWord);
          const raw = alignWords(targetWordsRef.current.map(normalizeWord), recognized);
          // Debounced against a single bad tick: a cheap beam_size=1 partial pass
          // occasionally mis-hears/hallucinates and self-corrects ~1.2s later, and
          // re-running the alignment DP over a growing recognized-word list can flip an
          // already-matched word's verdict even without any new mis-transcription. Only
          // promote a word's shown status once two consecutive partials agree on it —
          // otherwise hold whatever was last confirmed. Trades ~1.2s of extra latency
          // before a word's first verdict for not flashing a wrong one.
          const lastRaw = lastRawRef.current;
          setWordStatuses((confirmed) =>
            raw.map((status, i) => (status === lastRaw[i] && status !== confirmed[i] ? status : confirmed[i])),
          );
          lastRawRef.current = raw;
        } catch {
          // Malformed preview message — cosmetic feature, never worth surfacing an error.
        }
      };

      await new Promise<void>((resolve, reject) => {
        socket.onopen = () => resolve();
        socket.onerror = () => reject(new Error("Live preview socket failed to connect"));
      });

      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micStreamRef.current = micStream;
      const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      audioContextRef.current = audioContext;
      await audioContext.audioWorklet.addModule("/voice-pcm-worklet.js");

      const source = audioContext.createMediaStreamSource(micStream);
      const workletNode = new AudioWorkletNode(audioContext, "voice-pcm-processor");
      workletNodeRef.current = workletNode;
      workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (socket.readyState === WebSocket.OPEN) socket.send(event.data);
      };
      // Muted gain node, same reasoning as useVoiceSocket.ts: some browsers only keep
      // calling an AudioWorkletNode's process() while it's part of a graph reaching
      // the destination.
      const mute = audioContext.createGain();
      mute.gain.value = 0;
      source.connect(workletNode);
      workletNode.connect(mute);
      mute.connect(audioContext.destination);

      socketRef.current = socket;
    } catch (err) {
      console.error("[pronunciation-preview] failed to start:", err);
      teardown();
    }
  }, [getWsUrl, reset, teardown]);

  const stop = React.useCallback(() => {
    teardown();
  }, [teardown]);

  React.useEffect(() => teardown, [teardown]); // stop the mic/socket on unmount

  return { wordStatuses, start, stop, reset };
}
