"use client";

import * as React from "react";
import {
  Briefcase,
  History,
  Lock,
  Mic,
  Presentation,
  Sparkles,
  User,
  Video,
} from "lucide-react";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";
import { useActiveSessions } from "@/contexts/ActiveSessionsContext";
import { cn } from "@/lib/utils";

const SPEECH_TYPES = [
  {
    key: "business_pitch",
    label: "Business Pitch",
    description: "Practice delivering compelling business pitches with structure and persuasion analysis.",
    icon: Briefcase,
    input_mode: "audio",
  },
  {
    key: "casual_event",
    label: "Casual Event Speech",
    description: "Perfect toasts and wedding speeches with warmth and storytelling focus.",
    icon: Sparkles,
    input_mode: "audio",
  },
  {
    key: "motivational",
    label: "Motivational Speech",
    description: "Deliver inspiring, high-energy speeches with emotional impact analysis.",
    icon: User,
    input_mode: "audio",
  },
  {
    key: "classroom",
    label: "Classroom Presentation",
    description: "Practice academic presentations with structure, pacing, and filler word tracking.",
    icon: Presentation,
    input_mode: "audio",
  },
  {
    key: "ted_talk",
    label: "TED-Style Talk",
    description: "Craft narrative-driven, thought-provoking speeches with storytelling focus.",
    icon: Video,
    input_mode: "audio",
  },
];

export default function PublicSpeakingPage() {
  const { access } = useAssessmentAccess();
  const { publicSpeaking } = useActiveSessions();
  const isUnlocked = access?.access_level === "full_access";

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Public Speaking Coach
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Practice speeches and presentations with AI feedback on pacing, tone, structure, and delivery.
          Get detailed scorecards and actionable improvement tips.
        </p>
      </div>

      {publicSpeaking?.found ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm text-foreground">
          <History className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          You have an unfinished {publicSpeaking.label ?? "speech"} session — starting a new
          one below will end it.
        </div>
      ) : null}

      {!isUnlocked ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          {access?.locked_message ??
            "Complete your baseline assessment to unlock the Public Speaking Coach."}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {SPEECH_TYPES.map((speechType, index) => {
          const Icon = speechType.icon;
          const locked = !isUnlocked;
          const card = (
            <div
              className={cn(
                "group flex h-full animate-fade-up flex-col justify-between rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200",
                !locked && "cursor-pointer hover:-translate-y-1 hover:shadow-md",
                locked && "opacity-60",
              )}
              style={{ animationDelay: `${index * 70}ms` }}
            >
              <div>
                <div className="mb-6 flex items-start justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary transition-transform duration-300 group-hover:scale-110">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span className="flex items-center gap-1 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                    <Mic className="h-3 w-3" aria-hidden="true" />
                    Voice
                  </span>
                </div>
                <h3 className="font-serif text-lg font-semibold text-foreground">
                  {speechType.label}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">
                  {speechType.description}
                </p>
              </div>
              <div className="mt-6 text-sm font-medium text-primary">
                {locked ? (
                  <span className="text-muted-foreground">Complete assessment to unlock</span>
                ) : (
                  "Start Practicing"
                )}
              </div>
            </div>
          );

          return locked ? (
            <div key={speechType.key}>{card}</div>
          ) : (
            <a key={speechType.key} href={`/dashboard/public-speaking/${speechType.key}`}>
              {card}
            </a>
          );
        })}
      </div>
    </div>
  );
}
