import * as React from "react";
import { playText, stopCurrent } from "./tts";

interface SpeakableTurn {
  role: string;
  content: string;
}

/** Auto-speaks the latest assistant turn while `audioMode` is on. Re-speaks
 * the current last message right when audioMode flips on again too (not
 * just turns that arrive afterward) — otherwise toggling off then back on
 * looks broken since the "already played" guard blocks it silently. */
export function useAutoSpeak(
  audioMode: boolean,
  turns: SpeakableTurn[] | null | undefined,
) {
  const lastPlayed = React.useRef(-1);
  const wasOn = React.useRef(false);

  React.useEffect(() => {
    if (!audioMode || !turns?.length) {
      stopCurrent();
      wasOn.current = audioMode;
      return;
    }
    const turnedOn = !wasOn.current;
    wasOn.current = true;

    const lastIndex = turns.length - 1;
    const last = turns[lastIndex];
    if (last.role !== "assistant") return;

    if (turnedOn || lastPlayed.current !== lastIndex) {
      lastPlayed.current = lastIndex;
      playText(last.content);
    }
  }, [audioMode, turns]);
}
