"use client";

import * as React from "react";
import Image from "next/image";
import { toast } from "react-toastify";
import { Camera, ShieldCheck } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ApiError, API_ORIGIN } from "@/lib/api";
import {
  requestEmailChange,
  updateProfile,
  uploadAvatar,
  verifyEmailChange,
} from "@/lib/user";
import { useAuth } from "@/contexts/AuthContext";
import { getInitials } from "@/lib/utils";

const ROLE_LABELS: Record<string, string> = {
  ADMIN: "Administrator",
  USER: "Learner",
};

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const OTP_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 60;
const MAX_RESENDS = 3;

/**
 * US-04: editable name/email + avatar upload, wired to the real backend.
 *
 * Name saves immediately. Email changes go through a confirm step and then
 * an emailed OTP (same pattern as signup) instead of applying straight away
 * — without it, a typo could lock the user out, or silently hand the
 * account's login email to whoever actually owns that address.
 */
export function ProfileInfoSection() {
  const { user, setUser } = useAuth();
  const [name, setName] = React.useState(user?.name ?? "");
  const [email, setEmail] = React.useState(user?.email ?? "");
  const [fieldError, setFieldError] = React.useState<string | null>(null);
  const [isSaving, setIsSaving] = React.useState(false);
  const [isUploadingAvatar, setIsUploadingAvatar] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // Email-change flow: "confirm" the intent, then "otp" to verify the code
  // sent to the new address.
  const [emailStep, setEmailStep] = React.useState<"confirm" | "otp" | null>(null);
  const [pendingEmail, setPendingEmail] = React.useState("");
  const [otp, setOtp] = React.useState("");
  const [otpError, setOtpError] = React.useState<string | null>(null);
  const [isRequesting, setIsRequesting] = React.useState(false);
  const [isVerifying, setIsVerifying] = React.useState(false);
  const [isResending, setIsResending] = React.useState(false);
  const [resendCount, setResendCount] = React.useState(0);
  const [cooldown, setCooldown] = React.useState(RESEND_COOLDOWN_SECONDS);

  React.useEffect(() => {
    if (emailStep !== "otp" || cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [emailStep, cooldown]);

  if (!user) return null;

  const nameChanged = name.trim() !== user.name;
  const emailChanged = email.trim() !== user.email;
  const hasChanges = nameChanged || emailChanged;
  const resendsLeft = MAX_RESENDS - resendCount;

  function closeEmailModal() {
    setEmailStep(null);
    setPendingEmail("");
    setOtp("");
    setOtpError(null);
    setResendCount(0);
  }

  async function handleSave() {
    setFieldError(null);

    const trimmedName = name.trim();
    const trimmedEmail = email.trim();

    if (!trimmedName) {
      setFieldError("Name cannot be empty.");
      return;
    }
    if (!EMAIL_PATTERN.test(trimmedEmail)) {
      setFieldError("Enter a valid email address.");
      return;
    }

    if (nameChanged) {
      setIsSaving(true);
      try {
        const { user: updated } = await updateProfile({ name: trimmedName });
        setUser(updated);
        toast.success("Name updated.");
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Something went wrong.");
        setIsSaving(false);
        return;
      }
      setIsSaving(false);
    }

    if (emailChanged) {
      setPendingEmail(trimmedEmail);
      setEmailStep("confirm");
    }
  }

  async function handleConfirmEmailChange() {
    setIsRequesting(true);
    try {
      await requestEmailChange(pendingEmail);
      setEmailStep("otp");
      setCooldown(RESEND_COOLDOWN_SECONDS);
      toast.success(`Verification code sent to ${pendingEmail}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Something went wrong.");
      closeEmailModal();
    } finally {
      setIsRequesting(false);
    }
  }

  async function handleVerifyEmailOtp() {
    if (otp.trim().length !== OTP_LENGTH) {
      setOtpError(`Enter the ${OTP_LENGTH}-character code from your email.`);
      return;
    }

    setOtpError(null);
    setIsVerifying(true);
    try {
      const { user: updated } = await verifyEmailChange(otp.trim().toUpperCase());
      setUser(updated);
      toast.success("Email address updated.");
      closeEmailModal();
    } catch (err) {
      setOtpError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsVerifying(false);
    }
  }

  async function handleResendOtp() {
    if (resendCount >= MAX_RESENDS || cooldown > 0) return;

    setOtpError(null);
    setIsResending(true);
    try {
      await requestEmailChange(pendingEmail);
      setResendCount((prev) => prev + 1);
      setCooldown(RESEND_COOLDOWN_SECONDS);
      toast.success("Verification code resent.");
    } catch (err) {
      setOtpError(
        err instanceof ApiError ? err.message : "Couldn't resend the code. Try again shortly.",
      );
    } finally {
      setIsResending(false);
    }
  }

  async function handleAvatarChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setIsUploadingAvatar(true);
    try {
      const { user: updated } = await uploadAvatar(file);
      setUser(updated);
      toast.success("Profile photo updated.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't upload that image.");
    } finally {
      setIsUploadingAvatar(false);
    }
  }

  const hasCustomAvatar = user.avatarUrl && user.avatarUrl !== "user.webp";

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex items-center gap-4">
        <div className="relative">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploadingAvatar}
            className="group relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-secondary text-xl font-semibold text-primary disabled:opacity-70"
            aria-label="Change profile photo"
          >
            {hasCustomAvatar ? (
              <Image
                src={`${API_ORIGIN}/uploads/avatars/${user.avatarUrl}`}
                alt=""
                width={64}
                height={64}
                className="h-full w-full object-cover"
                unoptimized
              />
            ) : (
              getInitials(user.name)
            )}
            <span className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
              <Camera className="h-5 w-5 text-white" aria-hidden="true" />
            </span>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={handleAvatarChange}
          />
        </div>
        <div>
          <p className="text-lg font-semibold text-foreground">{user.name}</p>
          <span className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground">
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            {ROLE_LABELS[user.role] ?? user.role}
          </span>
        </div>
      </div>

      <div className="mt-6 flex flex-col gap-4 border-t border-border pt-6">
        <Input
          label="Full Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Input
          label="Email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          hint={emailChanged ? "We'll email a code to confirm this change." : undefined}
        />
        {fieldError ? <p className="text-sm text-danger">{fieldError}</p> : null}
        <Button
          type="button"
          size="sm"
          className="self-start"
          loading={isSaving}
          disabled={!hasChanges}
          onClick={handleSave}
        >
          Save Changes
        </Button>
      </div>

      <Modal
        open={emailStep !== null}
        onClose={isRequesting || isVerifying ? () => {} : closeEmailModal}
        title={emailStep === "otp" ? "Check your new inbox" : "Change your email?"}
        description={
          emailStep === "otp"
            ? `We sent a ${OTP_LENGTH}-character code to ${pendingEmail}.`
            : `We'll send a verification code to ${pendingEmail} to confirm this change. Your current email stays active until it's verified.`
        }
      >
        {emailStep === "confirm" ? (
          <div className="flex items-center gap-3">
            <Button
              type="button"
              size="sm"
              loading={isRequesting}
              onClick={handleConfirmEmailChange}
            >
              Send code
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isRequesting}
              onClick={closeEmailModal}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <Input
              label="Verification code"
              value={otp}
              onChange={(event) => setOtp(event.target.value.toUpperCase())}
              maxLength={OTP_LENGTH}
              autoComplete="one-time-code"
              error={otpError ?? undefined}
            />

            <Button
              type="button"
              size="sm"
              loading={isVerifying}
              disabled={otp.trim().length !== OTP_LENGTH}
              onClick={handleVerifyEmailOtp}
            >
              Verify &amp; Update Email
            </Button>

            <div className="flex items-center justify-between text-sm">
              <button
                type="button"
                onClick={handleResendOtp}
                disabled={cooldown > 0 || resendCount >= MAX_RESENDS || isResending}
                className="font-medium text-primary hover:text-primary-hover disabled:cursor-not-allowed disabled:text-muted-foreground"
              >
                {resendCount >= MAX_RESENDS
                  ? "No resends left"
                  : cooldown > 0
                    ? `Resend code in ${cooldown}s`
                    : isResending
                      ? "Sending..."
                      : "Resend code"}
              </button>
              {resendCount < MAX_RESENDS ? (
                <span className="text-xs text-muted-foreground">
                  {resendsLeft} resend{resendsLeft === 1 ? "" : "s"} left
                </span>
              ) : null}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
