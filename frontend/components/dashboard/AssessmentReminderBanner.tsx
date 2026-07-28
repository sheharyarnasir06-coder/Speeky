"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";

export function AssessmentReminderBanner() {
  const { access, isLoading } = useAssessmentAccess();
  const pathname = usePathname();

  // If we are still loading, or the prompt isn't required, render nothing.
  if (isLoading || !access?.show_assessment_prompt) {
    return null;
  }

  // Prevent the blocking overlay from showing if the user is already navigating
  // to the assessment page itself, or if they are just trying to manage their profile!
  if (
    pathname === "/dashboard/assessment" ||
    pathname === "/dashboard/profile"
  ) {
    return null;
  }

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm">
      <div className="flex w-full max-w-md animate-fade-up flex-col items-center gap-6 rounded-2xl border border-border bg-surface-elevated p-8 text-center shadow-xl">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-warning/10 text-warning">
          <Lock className="h-8 w-8" aria-hidden="true" />
        </div>

        <div className="flex flex-col gap-2">
          <h2 className="font-serif text-h2 font-semibold text-foreground">
            Assessment Required
          </h2>
          <p className="text-base text-muted-foreground">
            Complete your baseline assessment to unlock personalized learning
            features.
          </p>
        </div>

        <Button href="/dashboard/assessment" size="lg" className="mt-2 w-full">
          Take Assessment
        </Button>
      </div>
    </div>
  );
}
