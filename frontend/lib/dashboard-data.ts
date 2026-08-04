import {
  Briefcase,
  Compass,
  Home,
  Mic,
  Sparkles,
  TrendingUp,
  User,
  Users,
  Volume2,
  Wand2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface DashboardNavLink {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const DASHBOARD_NAV_LINKS: DashboardNavLink[] = [
  { label: "Home", href: "/dashboard", icon: Home },
  { label: "Explore", href: "/dashboard/explore", icon: Compass },
  { label: "Pronunciation", href: "/dashboard/pronunciation", icon: Volume2 },
  { label: "Accent", href: "/dashboard/accent-assessment", icon: Sparkles },
  { label: "Public Speaking", href: "/dashboard/public-speaking", icon: Mic },
  { label: "Rewrite Lab", href: "/dashboard/rewrite", icon: Wand2 },
  { label: "Progress", href: "/dashboard/progress", icon: TrendingUp },
  { label: "Profile", href: "/dashboard/profile", icon: User },
];

// Learning Mastery card labels — the values/sparkline bars themselves come from
// the real-time /progress-dashboard/progress data (see app/dashboard/page.tsx).
export interface MasteryMetricDef {
  id: "fluency" | "confidence" | "speech";
  label: string;
  description: string;
}

export const MASTERY_METRIC_DEFS: MasteryMetricDef[] = [
  { id: "fluency", label: "FLUENCY", description: "How smoothly you speak without long pauses or hesitation." },
  { id: "confidence", label: "CONFIDENCE", description: "How assured you sound across your practice sessions." },
  { id: "speech", label: "SPEECH", description: "How clear and accurate your pronunciation is." },
];

// ── Explore / "Choose Your Mission" catalog ─────────────────────────────────
// Mirrors UI Designs/choose_your_mission/code.html. "Choose Your Mission" itself
// is now populated from the real Scenario-Based Learning catalog (see lib/scenario.ts
// getScenarios(), wired in app/dashboard/explore/page.tsx) — these two static
// entries are kept because they point at other, already-shipped features
// (Interview Coach's own card lives above in the "AI Coach" section; Meeting Prep
// is a separate mockup feature, US-66) rather than Scenario-Based Learning.
//
// CM-US-05: categories are admin-managed and fetched dynamically (see
// lib/categories.ts + lib/icon-map.ts) — no longer a hardcoded union here.

export interface ExploreScenario {
  id: string;
  category: string;
  icon: LucideIcon;
  title: string;
  description: string;
  difficulty: string;
  featured?: boolean;
  href?: string;
}

export const EXPLORE_STATIC_SCENARIOS: ExploreScenario[] = [
  {
    id: "job-interview-prep",
    category: "Work",
    icon: Briefcase,
    title: "Job Interview Preparation",
    description:
      "Practice answering tough behavioral questions and negotiating your offer.",
    difficulty: "High Difficulty",
    featured: true,
    href: "/dashboard/interview-coach",
  },
  {
    id: "public-speaking-coach",
    category: "Work",
    icon: Mic,
    title: "Public Speaking Coach",
    description:
      "Practice speeches and presentations with AI feedback on pacing, tone, and delivery.",
    difficulty: "Intermediate",
    featured: true,
    href: "/dashboard/public-speaking",
  },
  {
    id: "meeting-new-colleagues",
    category: "Work",
    icon: Users,
    title: "Meeting Preparation",
    description:
      "Navigate small talk, agenda framing, and professional introductions.",
    difficulty: "Intermediate",
    href: "/dashboard/explore/meeting-prep",
  },
];