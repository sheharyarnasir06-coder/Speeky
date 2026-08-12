"use client";

import * as React from "react";
import Image from "next/image";
import { createPortal } from "react-dom";
import {
  Bell,
  Brain,
  ChevronRight,
  Lock,
  Mic,
  ShieldCheck,
  Target,
  Trash2,
  User,
  X,
  type LucideIcon,
} from "lucide-react";
import { AccessibilityProfileSection } from "@/components/dashboard/profile/AccessibilityProfileSection";
import { AssessmentSection } from "@/components/dashboard/profile/AssessmentSection";
import { CodeSwitchSection } from "@/components/dashboard/profile/CodeSwitchSection";
import { CodeSwitchWordListSection } from "@/components/dashboard/profile/CodeSwitchWordListSection";
import { ConversationMemorySection } from "@/components/dashboard/profile/ConversationMemorySection";
import { DangerZoneSection } from "@/components/dashboard/profile/DangerZoneSection";
import { LearningGoalSection } from "@/components/dashboard/profile/LearningGoalSection";
import { LocalAccentCalibrationSection } from "@/components/dashboard/profile/LocalAccentCalibrationSection";
import { NotificationPreferencesSection } from "@/components/dashboard/profile/NotificationPreferencesSection";
import { PerformanceMemorySection } from "@/components/dashboard/profile/PerformanceMemorySection";
import { PrivacyConsentSection } from "@/components/dashboard/profile/PrivacyConsentSection";
import { ProfileInfoSection } from "@/components/dashboard/profile/ProfileInfoSection";
import { SecuritySection } from "@/components/dashboard/profile/SecuritySection";
import { TargetAccentSection } from "@/components/dashboard/profile/TargetAccentSection";
import { useAuth } from "@/contexts/AuthContext";
import { API_ORIGIN } from "@/lib/api";
import { cn, getInitials } from "@/lib/utils";

type ProfileSettingsSection = {
  id: string;
  label: string;
  eyebrow: string;
  description: string;
  icon: LucideIcon;
  content: React.ReactNode;
};

interface ProfileSettingsModalProps {
  open: boolean;
  onClose: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  SUPER_ADMIN: "Super Admin",
  ADMIN: "Administrator",
  COMPLIANCE: "Compliance Officer",
  FINANCE: "Finance Admin",
  USER: "Learner",
};

export function ProfileSettingsModal({ open, onClose }: ProfileSettingsModalProps) {
  const { user } = useAuth();
  const [mounted, setMounted] = React.useState(false);
  const [activeSection, setActiveSection] = React.useState("public-profile");

  React.useEffect(() => setMounted(true), []);

  React.useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  if (!mounted || !open || !user) return null;

  const sections: ProfileSettingsSection[] = [
    {
      id: "public-profile",
      label: "Public profile",
      eyebrow: "Account identity",
      description: "Update your name, email, and profile photo.",
      icon: User,
      content: <ProfileInfoSection />,
    },
    {
      id: "learning",
      label: "Learning setup",
      eyebrow: "Assessment & goal",
      description: "Manage your baseline, target level, and learning focus.",
      icon: Target,
      content: (
        <>
          <LearningGoalSection />
          <AssessmentSection />
          <LocalAccentCalibrationSection />
        </>
      ),
    },
    {
      id: "privacy",
      label: "Privacy & consent",
      eyebrow: "Data controls",
      description: "Review privacy consent and account data choices.",
      icon: ShieldCheck,
      content: <PrivacyConsentSection />,
    },
    {
      id: "notifications",
      label: "Notifications",
      eyebrow: "Reminders",
      description: "Choose how and when Speeky should remind you.",
      icon: Bell,
      content: <NotificationPreferencesSection />,
    },
    {
      id: "memory",
      label: "Memory",
      eyebrow: "Coaching context",
      description: "View what Speeky remembers from your practice history.",
      icon: Brain,
      content: (
        <>
          <PerformanceMemorySection />
          <ConversationMemorySection />
        </>
      ),
    },
    {
      id: "speech-profile",
      label: "Speech profile",
      eyebrow: "Accent & accessibility",
      description: "Tune accent targets, code-switching, and accessibility preferences.",
      icon: Mic,
      content: (
        <>
          <TargetAccentSection />
          <AccessibilityProfileSection />
          <CodeSwitchSection />
          <CodeSwitchWordListSection />
        </>
      ),
    },
    {
      id: "security",
      label: "Security",
      eyebrow: "Sign-in safety",
      description: "Manage account security settings.",
      icon: Lock,
      content: <SecuritySection />,
    },
    {
      id: "danger-zone",
      label: "Danger zone",
      eyebrow: "Permanent actions",
      description: "Delete your Speeky account and data.",
      icon: Trash2,
      content: <DangerZoneSection />,
    },
  ];

  const selected = sections.find((section) => section.id === activeSection) ?? sections[0];
  const hasCustomAvatar = user.avatarUrl && user.avatarUrl !== "user.webp";

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-3 sm:p-6">
      <button
        type="button"
        aria-label="Close profile settings"
        className="absolute inset-0 bg-primary/18 backdrop-blur-md dark:bg-background/70"
        onClick={onClose}
      />

      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-settings-title"
        className="relative grid h-[86dvh] max-h-[790px] w-full max-w-[86rem] animate-fade-up overflow-hidden rounded-[2rem] border border-border bg-surface-elevated shadow-[0_28px_90px_hsl(var(--foreground)/0.20)] md:grid-cols-[19rem_1fr]"
      >
        <aside className="flex min-h-0 flex-col border-b border-border bg-surface/85 p-4 md:border-b-0 md:border-r md:p-5">
          <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface-elevated p-3 shadow-sm">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-secondary text-sm font-semibold text-primary">
              {hasCustomAvatar ? (
                <Image
                  src={`${API_ORIGIN}/uploads/avatars/${user.avatarUrl}`}
                  alt=""
                  width={48}
                  height={48}
                  className="h-full w-full object-cover"
                  unoptimized
                />
              ) : (
                getInitials(user.name)
              )}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold text-foreground">{user.name}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {ROLE_LABELS[user.role] ?? user.role}
              </span>
            </span>
          </div>

          <nav
            aria-label="Profile settings sections"
            className="mt-4 flex gap-2 overflow-x-auto pb-1 md:min-h-0 md:flex-1 md:flex-col md:overflow-y-auto md:overflow-x-hidden md:pb-0"
          >
            {sections.map((section) => {
              const Icon = section.icon;
              const isActive = section.id === selected.id;

              return (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => setActiveSection(section.id)}
                  className={cn(
                    "group flex min-w-max items-center gap-3 rounded-2xl px-3 py-3 text-left text-sm font-medium transition-colors md:min-w-0",
                    isActive
                      ? "bg-primary text-white shadow-sm ring-2 ring-primary/20 ring-offset-2 ring-offset-surface"
                      : "text-muted-foreground hover:bg-surface-elevated hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="truncate">{section.label}</span>
                  <ChevronRight
                    className={cn(
                      "ml-auto hidden h-4 w-4 transition-transform md:block",
                      isActive ? "text-white" : "text-muted-foreground group-hover:translate-x-0.5",
                    )}
                    aria-hidden
                  />
                </button>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-h-0 flex-col bg-background/65">
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border bg-surface-elevated/45 px-5 py-5 sm:px-8">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                {selected.eyebrow}
              </p>
              <h1 id="profile-settings-title" className="mt-1 font-serif text-2xl font-semibold text-foreground sm:text-3xl">
                {selected.label}
              </h1>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{selected.description}</p>
            </div>
            <button
              type="button"
              aria-label="Close profile settings"
              onClick={onClose}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-border bg-surface-elevated text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-6">
            <div className="mx-auto flex max-w-3xl flex-col gap-5">{selected.content}</div>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}
