"use client";

/**
 * A silent audience member to deliver the speech to, shown during the speech phase itself.
 *
 * The avatar here never speaks and never listens: the backend starts it with no STT, LLM or TTS
 * at all (live_call/worker.py `_run_idle_audience`), which is what makes it safe to have in the
 * room while the mic is recording audio that gets scored. It is presence, not conversation —
 * the talking avatar belongs to the Q&A phase (LiveCallModal) and is gated separately.
 *
 * Hiding it must never touch session state: this is decoration on top of a recording in
 * progress, so there is no onEnded and nothing to submit.
 *
 * Renders as a bare grid item, not a card. It sits beside the speaker's own self-view in the
 * recording screen's stage grid, matching the Q&A screen's you-and-them layout — the point of an
 * audience is looking at it while watching your own delivery, which the old centred card below
 * the fold could not do. The caller owns the grid; this owns one cell.
 */

import * as React from "react";
import { EyeOff, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useLiveCallConnection } from "@/lib/useLiveCallConnection";

// Panel is not reused here: its caption is a plain label, and this cell needs the Hide control
// on that same row. The box below is Panel's own markup, kept in sync deliberately.
import { AvatarRoom, AvatarVideo } from "./AvatarVideoPanel";

interface IdleAudiencePanelProps {
  sessionId: string;
  /** The session must still be in_progress; the token request fails otherwise. */
  active: boolean;
  onHide: () => void;
}

export function IdleAudiencePanel({ sessionId, active, onHide }: IdleAudiencePanelProps) {
  const { connection, connecting, error, disconnect } = useLiveCallConnection(
    "public_speaking",
    sessionId,
    active,
    "idle",
  );

  function handleHide() {
    disconnect();
    onHide();
  }

  if (!active) return null;

  return (
    <div className="flex flex-col gap-1">
      {/* The caption row doubles as the panel's own controls, which is what lets the card chrome
          go — a second bordered card inside a grid cell reads as a nested dialog. */}
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Users className="h-3.5 w-3.5 text-primary" />
          Your audience
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleHide}
          className="!h-auto !px-1.5 !py-0.5 text-xs text-muted-foreground"
        >
          <EyeOff className="mr-1 h-3.5 w-3.5" />
          Hide
        </Button>
      </div>

      <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-black">
        {/* Failing here costs the user nothing — the speech records and scores exactly the
            same with an empty panel, so this stays a caption rather than an error. */}
        <AvatarRoom
          connection={connection}
          connecting={connecting}
          tokenError={error}
          errorText="No audience available right now — carry on, your speech still records."
          publishAudio={false}
          onDisconnected={onHide}
        >
          <AvatarVideo idleCaption="Waiting for your audience…" />
        </AvatarRoom>
      </div>
    </div>
  );
}
