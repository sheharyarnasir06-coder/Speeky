"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { getOpenExploreSession, getResumablePublicSpeaking, type OpenExploreSession, type ResumablePublicSpeaking } from "@/lib/activeSessions";
import { checkResumableSession, type ResumeCheck } from "@/lib/pronunciation";
import { useAuth } from "@/contexts/AuthContext";

interface ActiveSessionsContextValue {
  explore: OpenExploreSession | null;
  publicSpeaking: ResumablePublicSpeaking | null;
  pronunciation: ResumeCheck | null;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

const ActiveSessionsContext = React.createContext<ActiveSessionsContextValue | undefined>(undefined);

/**
 * Cross-feature "you have an unfinished session" state — one fetch on dashboard
 * load, consumed by the Explore/Public Speaking resume banners and the Sidebar's
 * resume indicators, so none of them re-derive this independently.
 */
export function ActiveSessionsProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const [explore, setExplore] = React.useState<OpenExploreSession | null>(null);
  const [publicSpeaking, setPublicSpeaking] = React.useState<ResumablePublicSpeaking | null>(null);
  const [pronunciation, setPronunciation] = React.useState<ResumeCheck | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    if (!user) {
      setExplore(null);
      setPublicSpeaking(null);
      setPronunciation(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    const [exploreResult, psResult, pronResult] = await Promise.allSettled([
      getOpenExploreSession(),
      getResumablePublicSpeaking(),
      checkResumableSession(),
    ]);
    setExplore(exploreResult.status === "fulfilled" ? exploreResult.value : null);
    setPublicSpeaking(psResult.status === "fulfilled" ? psResult.value : null);
    setPronunciation(pronResult.status === "fulfilled" ? pronResult.value : null);
    setIsLoading(false);
    // pathname triggers re-fetch on every client-side navigation so resume banners
    // and sidebar dots reflect the current backend state without a hard refresh.
  }, [user, pathname]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <ActiveSessionsContext.Provider value={{ explore, publicSpeaking, pronunciation, isLoading, refresh }}>
      {children}
    </ActiveSessionsContext.Provider>
  );
}

export function useActiveSessions() {
  const ctx = React.useContext(ActiveSessionsContext);
  if (!ctx) {
    throw new Error("useActiveSessions must be used within an ActiveSessionsProvider");
  }
  return ctx;
}
