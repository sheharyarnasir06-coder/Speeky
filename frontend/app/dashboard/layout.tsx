"use client";

import * as React from "react";
import { useRouter, usePathname } from "next/navigation";
import { LogOut, Menu } from "lucide-react";
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
import { PageTransition } from "@/components/common/PageTransition";
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
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);

  React.useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  React.useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

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
      <div className="flex min-h-screen bg-background dark:bg-[radial-gradient(60%_50%_at_12%_-8%,hsl(var(--accent)/0.12),transparent_60%),radial-gradient(55%_45%_at_100%_8%,hsl(var(--primary)/0.16),transparent_55%),radial-gradient(60%_45%_at_50%_115%,hsl(var(--accent)/0.08),transparent_60%)]">
        <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center gap-2 border-b border-border px-4 sm:gap-3 sm:px-6 lg:px-10">
            <button
              type="button"
              aria-label="Open menu"
              className="-ml-1.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-foreground hover:bg-surface lg:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              <Menu className="h-5 w-5" aria-hidden="true" />
            </button>
            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <VoiceStatusWidget />
              <StreakNavIcon />
              <ThemeToggle />
              <Button variant="ghost" size="sm" onClick={handleLogout}>
                <LogOut className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">Logout</span>
              </Button>
            </div>
          </header>

          <main className="relative flex-1 px-4 py-6 sm:px-6 sm:py-8 lg:px-10 lg:py-8">
            <AssessmentReminderBanner />
            <PendingNotificationsBanner />
            <OveruseNudgeBanner />
            <StreakWarningBanner />
            <PageTransition>{children}</PageTransition>
          </main>
        </div>
      </div>
    </ActiveSessionsProvider>
    </AssessmentProvider>
    </ConsentGate>
  );
}
