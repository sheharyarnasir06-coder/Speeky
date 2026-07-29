"use client";

import * as React from "react";
import { useAuth } from "@/contexts/AuthContext";
import { API_ORIGIN } from "@/lib/api";
import { cn } from "@/lib/utils";

interface UserChatAvatarProps {
  className?: string;
  size?: "sm" | "md";
}

const SIZE_CLASSES = {
  sm: "h-7 w-7 text-[10px]",
  md: "h-9 w-9 text-xs",
};

function getInitials(name?: string | null, email?: string | null) {
  const source = name?.trim() || email?.split("@")[0] || "You";
  const parts = source.split(/\s+/).filter(Boolean);

  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  return source.slice(0, 2).toUpperCase();
}

function resolveAvatarUrl(avatarUrl?: string | null) {
  const value = avatarUrl?.trim();
  if (!value) return "";

  if (
    value.startsWith("http://") ||
    value.startsWith("https://") ||
    value.startsWith("data:") ||
    value.startsWith("blob:")
  ) {
    return value;
  }

  if (value.startsWith("/uploads/")) {
    return `${API_ORIGIN}${value}`;
  }

  if (value.startsWith("uploads/")) {
    return `${API_ORIGIN}/${value}`;
  }

  return `${API_ORIGIN}/uploads/avatars/${value}`;
}

export function UserChatAvatar({ className, size = "md" }: UserChatAvatarProps) {
  const { user } = useAuth();
  const avatarUrl = resolveAvatarUrl(user?.avatarUrl);
  const [imageFailed, setImageFailed] = React.useState(false);
  const initials = getInitials(user?.name, user?.email);

  React.useEffect(() => {
    setImageFailed(false);
  }, [avatarUrl]);

  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-primary/20 bg-primary text-primary-foreground shadow-sm ring-2 ring-background",
        SIZE_CLASSES[size],
        className,
      )}
      aria-label="You"
      role="img"
    >
      {avatarUrl && !imageFailed ? (
        <img
          src={avatarUrl}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <span className="font-semibold leading-none">{initials}</span>
      )}
    </span>
  );
}
