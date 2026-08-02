"use client";

import * as React from "react";
import { ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface RegionConfidenceBadgeProps {
  note: string;
}

/** E-03: a visible caveat — never silently presenting spoofing-suspected
 * regional data as fully reliable. Icon + label, not color alone. */
export function RegionConfidenceBadge({ note }: RegionConfidenceBadgeProps) {
  return (
    <Badge tone="warning" title={note} className="gap-1">
      <ShieldAlert className="h-3 w-3" aria-hidden="true" />
      Lower confidence
    </Badge>
  );
}
