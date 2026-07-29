import Image from "next/image";
import { cn } from "@/lib/utils";

interface AiCoachAvatarProps {
  className?: string;
  size?: "sm" | "md";
}

const SIZE_CLASSES = {
  sm: "h-7 w-7",
  md: "h-9 w-9",
};

const IMAGE_SIZE = {
  sm: 24,
  md: 30,
};

export function AiCoachAvatar({ className, size = "md" }: AiCoachAvatarProps) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-white shadow-sm ring-2 ring-background",
        SIZE_CLASSES[size],
        className,
      )}
      aria-label="AI coach"
      role="img"
    >
      <Image
        src="/ai-coach-avatar.png"
        alt=""
        width={IMAGE_SIZE[size]}
        height={IMAGE_SIZE[size]}
        className="h-auto w-auto object-contain"
      />
    </span>
  );
}
