"use client";

/**
 * The 16:9 captioned video box, and its placeholder state.
 *
 * Deliberately its own module, LiveKit-free. These two live beside the avatar components they
 * were written for, but the speech screen's self-view wants the same box without any of the room
 * wiring — and importing them from AvatarVideoPanel pulls @livekit/components-react (~150kB)
 * into whatever imports it. Doing exactly that took the Public Speaking page's First Load from
 * 140kB to 291kB, undoing the dynamic-import split that file's own header warns about.
 */

import * as React from "react";
import { Loader2 } from "lucide-react";

export function Panel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-black">
        {children}
      </div>
    </div>
  );
}

export function PanelPlaceholder({ text, spinner }: { text: string; spinner?: boolean }) {
  return (
    <div className="flex h-full w-full items-center justify-center gap-2 px-4 text-center text-xs text-white/80">
      {spinner ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {text}
    </div>
  );
}
