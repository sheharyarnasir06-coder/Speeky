"use client";

import { cn } from "@/lib/utils";

interface VoiceWaveProps {
  className?: string;
  compact?: boolean;
}

const PATHS = [
  "M-80 112 C 80 70, 178 42, 292 72 S 460 160, 612 92 S 820 34, 1016 110 S 1260 136, 1430 72",
  "M-80 132 C 96 84, 192 60, 310 91 S 470 174, 626 110 S 840 50, 1026 126 S 1248 156, 1430 92",
  "M-80 152 C 112 98, 210 80, 326 112 S 482 190, 642 130 S 860 74, 1036 145 S 1244 176, 1430 118",
  "M-80 172 C 128 118, 226 100, 342 132 S 492 208, 660 150 S 880 96, 1044 166 S 1242 198, 1430 142",
  "M-80 192 C 144 138, 244 122, 360 154 S 506 230, 678 172 S 902 118, 1054 188 S 1240 218, 1430 166",
  "M-80 212 C 160 158, 262 144, 380 176 S 520 250, 698 196 S 922 142, 1064 210 S 1238 238, 1430 190",
];

export function VoiceWave({ className, compact = false }: VoiceWaveProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-x-0 overflow-hidden opacity-60 [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]",
        compact ? "h-28" : "h-56",
        className,
      )}
    >
      <svg
        viewBox="0 0 1340 300"
        preserveAspectRatio="none"
        className="voice-wave-ribbon h-full w-[150%]"
      >
        <defs>
          <linearGradient id="speeky-wave-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.08" />
            <stop offset="35%" stopColor="hsl(var(--accent))" stopOpacity="0.72" />
            <stop offset="70%" stopColor="hsl(var(--primary))" stopOpacity="0.42" />
            <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity="0.1" />
          </linearGradient>
        </defs>
        <g fill="none" stroke="url(#speeky-wave-gradient)" strokeWidth="1">
          {PATHS.map((path, index) => (
            <path
              key={path}
              d={path}
              className="voice-wave-line"
              style={{ animationDelay: `${index * -0.9}s` }}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}
