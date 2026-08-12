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
import { useAuth } from "@/contexts/AuthContext";
import { AssessmentProvider } from "@/contexts/AssessmentContext";
import { ActiveSessionsProvider } from "@/contexts/ActiveSessionsContext";
import { ThemeToggle } from "@/components/ui/theme-toggle";

const AMBIENT_BACKDROP_ROUTES = new Set([
  "/dashboard/pronunciation",
  "/dashboard/accent-assessment",
  "/dashboard/rewrite",
  "/dashboard/admin",
]);

function DashboardAmbientBackdrop({ pathname }: { pathname: string }) {
  if (!AMBIENT_BACKDROP_ROUTES.has(pathname)) return null;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-0 hidden overflow-hidden lg:block"
    >
      <span
        className="absolute -left-16 top-16 h-44 w-44 rounded-br-[6rem] rounded-tr-[6rem] bg-secondary/80 dark:bg-primary/[0.10]"
      />
      <span
        className="absolute -right-16 bottom-10 h-48 w-48 rounded-full bg-danger/10 dark:bg-danger/[0.09]"
      />
    </div>
  );
}

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
      <div className="flex min-h-screen bg-[radial-gradient(50%_38%_at_12%_-8%,hsl(var(--primary)/0.12),transparent_60%),radial-gradient(44%_34%_at_96%_4%,hsl(var(--accent)/0.10),transparent_60%),radial-gradient(38%_28%_at_72%_110%,hsl(var(--danger)/0.08),transparent_62%),hsl(var(--background))] dark:bg-[radial-gradient(60%_50%_at_12%_-8%,hsl(var(--primary)/0.14),transparent_60%),radial-gradient(55%_45%_at_100%_8%,hsl(var(--accent)/0.10),transparent_55%),radial-gradient(50%_38%_at_74%_112%,hsl(var(--danger)/0.08),transparent_60%),hsl(var(--background))]">
        <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center gap-2 border-b border-border bg-background/72 px-4 backdrop-blur-xl sm:gap-3 sm:px-6 lg:px-10">
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
            <DashboardAmbientBackdrop pathname={pathname} />

            <div className="relative z-10">
              <AssessmentReminderBanner />
              <PendingNotificationsBanner />
              <OveruseNudgeBanner />
              <StreakWarningBanner />
            </div>

            {/* Page Transition */}
            <div
              key={pathname}
              className="relative z-10 animate-[fade-up_300ms_cubic-bezier(0.22,1,0.36,1)]"
            >
              {children}
            </div>
          </main>
        </div>
      </div>
    </ActiveSessionsProvider>
    </AssessmentProvider>
    </ConsentGate>
  );
}
