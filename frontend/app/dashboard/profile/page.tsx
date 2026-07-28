"use client";

import { useAuth } from "@/contexts/AuthContext";
import { ProfileInfoSection } from "@/components/dashboard/profile/ProfileInfoSection";
import { LearningGoalSection } from "@/components/dashboard/profile/LearningGoalSection";
import { AssessmentSection } from "@/components/dashboard/profile/AssessmentSection";
import { PerformanceMemorySection } from "@/components/dashboard/profile/PerformanceMemorySection";
import { PrivacyConsentSection } from "@/components/dashboard/profile/PrivacyConsentSection";
import { NotificationPreferencesSection } from "@/components/dashboard/profile/NotificationPreferencesSection";
import { ConversationMemorySection } from "@/components/dashboard/profile/ConversationMemorySection";
import { CodeSwitchSection } from "@/components/dashboard/profile/CodeSwitchSection";
import { CodeSwitchWordListSection } from "@/components/dashboard/profile/CodeSwitchWordListSection";
import { TargetAccentSection } from "@/components/dashboard/profile/TargetAccentSection";
import { AccessibilityProfileSection } from "@/components/dashboard/profile/AccessibilityProfileSection";
import { SecuritySection } from "@/components/dashboard/profile/SecuritySection";
import { DangerZoneSection } from "@/components/dashboard/profile/DangerZoneSection";

import { LocalAccentCalibrationSection } from "@/components/dashboard/profile/LocalAccentCalibrationSection";

export default function ProfilePage() {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <h1 className="font-serif text-h1 font-semibold text-foreground">
        Profile
      </h1>

      <ProfileInfoSection />
      <LearningGoalSection />
      <AssessmentSection />
      <LocalAccentCalibrationSection />
      <PerformanceMemorySection />
      <PrivacyConsentSection />
      <NotificationPreferencesSection />
      <ConversationMemorySection />
      <TargetAccentSection />
      <AccessibilityProfileSection />
      <CodeSwitchSection />
      <CodeSwitchWordListSection />
      <SecuritySection />
      <DangerZoneSection />
    </div>
  );
}
