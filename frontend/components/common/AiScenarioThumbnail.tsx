"use client";

import Image from "next/image";

import { cn } from "@/lib/utils";

const AI_AVATAR_THUMBNAIL_SRC = "/ai-scenario-thumbnail.png";

interface AiScenarioCardArtProps {
  title: string;
  locked?: boolean;
}

export function AiScenarioCardArt({
  title,
  locked = false,
}: AiScenarioCardArtProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-0 right-0 top-0 hidden w-[43%] overflow-hidden sm:block",
        locked && "opacity-70",
      )}
      aria-hidden="true"
    >
      <span className="absolute inset-0 bg-secondary/70 dark:bg-secondary/25" />
      <Image
        src={AI_AVATAR_THUMBNAIL_SRC}
        alt=""
        fill
        sizes="(min-width: 1024px) 300px, 43vw"
        className="object-cover object-center opacity-90 saturate-95 transition-transform duration-500 group-hover:scale-[1.04] dark:opacity-80"
      />
      <span
        className="absolute inset-y-0 -left-10 w-20 bg-surface-elevated"
        style={{ clipPath: "polygon(0 0, 52% 0, 100% 100%, 0 100%)" }}
      />
      <span
        className="absolute inset-y-0 -left-11 w-24 border-l border-border/80"
        style={{ clipPath: "polygon(46% 0, 54% 0, 100% 100%, 92% 100%)" }}
      />
      <span className="absolute inset-0 bg-gradient-to-l from-transparent via-transparent to-surface-elevated/20" />
      <span className="sr-only">{`${title} AI coach avatar`}</span>
    </div>
  );
}
