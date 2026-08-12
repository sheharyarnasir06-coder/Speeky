"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { ProfileSettingsModal } from "@/components/dashboard/profile/ProfileSettingsModal";

export default function ProfilePage() {
  const { user } = useAuth();
  const router = useRouter();
  const [open, setOpen] = React.useState(true);

  if (!user) return null;

  function handleClose() {
    setOpen(false);
    router.push("/dashboard");
  }

  return (
    <ProfileSettingsModal open={open} onClose={handleClose} />
  );
}
