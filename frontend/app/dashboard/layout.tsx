"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { AssessmentReminderBanner } from "@/components/dashboard/AssessmentReminderBanner";
import { PendingNotificationsBanner } from "@/components/dashboard/PendingNotificationsBanner";
import { OveruseNudgeBanner } from "@/components/dashboard/OveruseNudgeBanner";
import { StreakWarningBanner } from "@/components/dashboard/StreakWarningBanner";
import { StreakNavIcon } from "@/components/dashboard/StreakNavIcon";
import { LearningGoalGate } from "@/components/dashboard/LearningGoalGate";
import { ConsentGate } from "@/components/dashboard/ConsentGate";
import { VoiceStatusWidget } from "@/components/common/VoiceStatusWidget";
import { useAuth } from "@/contexts/AuthContext";
import { AssessmentProvider } from "@/contexts/AssessmentContext";
import { ActiveSessionsProvider } from "@/contexts/ActiveSessionsContext";
import { ThemeToggle } from "@/components/ui/theme-toggle";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <span
          className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent text-muted-foreground"
          aria-hidden="true"
        />
      </div>
    );
  }

  // US-08 fallback: pre-existing accounts never picked a goal (backfilled
  // learningGoalSet=false) — block the whole dashboard behind the same mandatory
  // choice new signups make, instead of a dismissible banner, so gating stays real.
  if (!user.learningGoalSet) {
    return (
      <ConsentGate>
        <LearningGoalGate />
      </ConsentGate>
    );
  }

  return (
    <ConsentGate>
    <AssessmentProvider>
    <ActiveSessionsProvider>
      <div className="flex min-h-screen bg-background">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center justify-end gap-3 border-b border-border px-6 lg:px-10">
            <VoiceStatusWidget />
            <StreakNavIcon />
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={handleLogout}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Logout
            </Button>
          </header>

          <main className="relative flex-1 px-6 py-8 lg:px-10">
            <AssessmentReminderBanner />
            <PendingNotificationsBanner />
            <OveruseNudgeBanner />
            <StreakWarningBanner />
            {children}
          </main>
        </div>
      </div>
    </ActiveSessionsProvider>
    </AssessmentProvider>
    </ConsentGate>
  );
}
