"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

// Re-keying by pathname forces React to remount this wrapper on every dashboard
// navigation, which replays `animate-fade-up` — the "page flash" the sidebar/header
// (which live outside this wrapper, in DashboardLayout) never lose their state for.
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div key={pathname} className="animate-fade-up">
      {children}
    </div>
  );
}
