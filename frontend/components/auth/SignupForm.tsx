"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "react-toastify";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { resendSignupOtp, signup, verifySignupOtp } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";
import {
  LEARNING_GOALS,
  saveLearningGoal,
  type LearningGoal,
} from "@/lib/goals";
import { LegalModal } from "@/components/common/LegalModal";
import {
  EMAIL_DOMAIN_ERROR,
  NAME_RULE_ERROR,
  PASSWORD_RULE_ERROR,
  isAllowedEmailDomain,
  isValidName,
  isValidPassword,
} from "@/lib/validation";

interface SignupFieldValues {
  firstName: string;
  lastName: string;
  email: string;
  password: string;
  confirmPassword: string;
}

export interface SignupSubmitValues {
  fullName: string;
  email: string;
  password: string;
}

interface SignupFormProps {
  onSubmit?: (values: SignupSubmitValues) => Promise<void> | void;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const OTP_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 60;
const MAX_RESENDS = 3;

function validate(values: SignupFieldValues) {
  const errors: Partial<Record<keyof SignupFieldValues, string>> = {};

  const fullName =
    `${values.firstName.trim()} ${values.lastName.trim()}`.trim();
  if (!values.firstName.trim()) {
    errors.firstName = "First name is required.";
  }
  if (!values.lastName.trim()) {
    errors.lastName = "Last name is required.";
  }
  if (!errors.firstName && !errors.lastName && !isValidName(fullName)) {
    errors.lastName = NAME_RULE_ERROR;
  }

  if (!values.email.trim()) {
    errors.email = "Email is required.";
  } else if (!EMAIL_PATTERN.test(values.email.trim())) {
    errors.email = "Enter a valid email address.";
  } else if (!isAllowedEmailDomain(values.email)) {
    errors.email = EMAIL_DOMAIN_ERROR;
  }

  if (!values.password) {
    errors.password = "Password is required.";
  } else if (!isValidPassword(values.password)) {
    errors.password = PASSWORD_RULE_ERROR;
  }

  if (!values.confirmPassword) {
    errors.confirmPassword = "Confirm your password.";
  } else if (values.confirmPassword !== values.password) {
    errors.confirmPassword = "Passwords do not match.";
  }

  return errors;
}

/**
 * Three-step signup: (1) credentials, (2) email OTP verification, (3) mandatory
 * learning-goal selection (US-08 AC). The backend creates no account and no
 * session until the emailed code is verified (signup only queues a pending row +
 * sends the code), so the goal step MUST come after verification — there is no
 * user row to attach it to before then. Once verified, the goal is PATCHed onto
 * the real profile (users.learningGoal) rather than kept client-side.
 * Resend is gated client-side: 60s cooldown, 3 resends max per signup attempt
 * (the backend itself has no such limit).
 *
 * Google/Apple SSO (also called for in US-08) has no backend support at
 * all (no OAuth routes exist), so those buttons are shown disabled rather
 * than faked. TODO(backend): add SSO routes, then wire these up for real.
 */
export function SignupForm({ onSubmit }: SignupFormProps) {
  const router = useRouter();
  const { setUser } = useAuth();
  const [step, setStep] = React.useState<"credentials" | "otp" | "goal">(
    "credentials",
  );
  const [values, setValues] = React.useState<SignupFieldValues>({
    firstName: "",
    lastName: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [touched, setTouched] = React.useState<
    Partial<Record<keyof SignupFieldValues, boolean>>
  >({});
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [agreedToTerms, setAgreedToTerms] = React.useState(false);
  const [agreeTouched, setAgreeTouched] = React.useState(false);
  const [goal, setGoal] = React.useState<LearningGoal | null>(null);
  const [legalType, setLegalType] = React.useState<"terms" | "privacy" | null>(null);

  const [otp, setOtp] = React.useState("");
  const [otpError, setOtpError] = React.useState<string | null>(null);
  const [isVerifying, setIsVerifying] = React.useState(false);
  const [resendCount, setResendCount] = React.useState(0);
  const [isResending, setIsResending] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(RESEND_COOLDOWN_SECONDS);

  const errors = validate(values);
  const agreeError =
    agreeTouched && !agreedToTerms
      ? "You must agree to the Terms & Conditions to continue."
      : undefined;

  React.useEffect(() => {
    if (step !== "otp" || cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [step, cooldown]);

  function handleChange(field: keyof SignupFieldValues, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  function handleBlur(field: keyof SignupFieldValues) {
    setTouched((prev) => ({ ...prev, [field]: true }));
  }

  async function handleContinue(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched({
      firstName: true,
      lastName: true,
      email: true,
      password: true,
      confirmPassword: true,
    });
    setAgreeTouched(true);

    const currentErrors = validate(values);
    if (Object.keys(currentErrors).length > 0 || !agreedToTerms) {
      return;
    }

    const fullName =
      `${values.firstName.trim()} ${values.lastName.trim()}`.trim();

    try {
      setIsSubmitting(true);
      setFormError(null);
      if (onSubmit) {
        await onSubmit({
          fullName,
          email: values.email.trim(),
          password: values.password,
        });
      } else {
        await signup({
          name: fullName,
          email: values.email.trim(),
          password: values.password,
        });
        setStep("otp");
        setCooldown(RESEND_COOLDOWN_SECONDS);
      }
    } catch (error) {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleVerifyOtp() {
    if (otp.trim().length !== OTP_LENGTH) {
      setOtpError(`Enter the ${OTP_LENGTH}-character code from your email.`);
      return;
    }

    setOtpError(null);
    setIsVerifying(true);
    try {
      const { user } = await verifySignupOtp({
        email: values.email.trim(),
        code: otp.trim().toUpperCase(),
      });
      // Account + session now exist. Log the user in here (rather than after the
      // goal step) so the goal PATCH below is an authenticated call, and so a
      // user who closes the tab mid-goal-step is still signed up.
      setUser(user);
      setStep("goal");
    } catch (error) {
      setOtpError(
        error instanceof ApiError
          ? error.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setIsVerifying(false);
    }
  }

  async function handleSaveGoal() {
    if (!goal) return;

    setIsSubmitting(true);
    setFormError(null);
    try {
      const { user } = await saveLearningGoal(goal);
      setUser(user);
      toast.success(`Welcome to Speeky, ${user.name.split(" ")[0]}!`);
      router.push("/dashboard");
    } catch (error) {
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Couldn't save your goal. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleResendOtp() {
    if (resendCount >= MAX_RESENDS || cooldown > 0) return;

    setOtpError(null);
    setIsResending(true);
    try {
      await resendSignupOtp(values.email.trim());
      setResendCount((prev) => prev + 1);
      setCooldown(RESEND_COOLDOWN_SECONDS);
      toast.success("Verification code resent.");
    } catch (error) {
      setOtpError(
        error instanceof ApiError
          ? error.message
          : "Couldn't resend the code. Try again shortly.",
      );
    } finally {
      setIsResending(false);
    }
  }

  if (step === "otp") {
    const resendsLeft = MAX_RESENDS - resendCount;
    return (
      <div className="flex flex-col gap-5">
        <div>
          <p className="text-sm font-medium text-foreground">
            Check your email
          </p>
          <p className="text-sm text-muted-foreground">
            We sent a {OTP_LENGTH}-character code to{" "}
            <strong className="text-foreground">{values.email.trim()}</strong>.
          </p>
        </div>

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
          size="lg"
          loading={isVerifying}
          disabled={otp.trim().length !== OTP_LENGTH}
          onClick={handleVerifyOtp}
        >
          Verify &amp; Create Account
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

        <button
          type="button"
          onClick={() => setStep("credentials")}
          className="text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          Back
        </button>
      </div>
    );
  }

  if (step === "goal") {
    return (
      <div className="flex flex-col gap-5">
        <div>
          <p className="text-sm font-medium text-foreground">
            Email verified — what&apos;s your main goal?
          </p>
          <p className="text-sm text-muted-foreground">
            We&apos;ll save this to your profile and tailor your dashboard,
            daily challenge, and recommended scenarios around it. You can change
            it any time from your profile.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {LEARNING_GOALS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setGoal(option.id)}
              className={cn(
                "rounded-xl border p-4 text-left transition-colors",
                goal === option.id
                  ? "border-primary bg-secondary"
                  : "border-border hover:bg-surface",
              )}
            >
              <p className="text-sm font-semibold text-foreground">
                {option.label}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {option.description}
              </p>
            </button>
          ))}
        </div>

        {formError ? <p className="text-sm text-danger">{formError}</p> : null}

        {/* No "Back" here: the account and session already exist by this point,
            so there is nothing to go back to. */}
        <Button
          type="button"
          size="lg"
          loading={isSubmitting}
          disabled={!goal}
          onClick={handleSaveGoal}
        >
          Finish Setup
        </Button>
      </div>
    );
  }

  return (
    <>
      <form
        onSubmit={handleContinue}
        noValidate
        className="flex flex-col gap-5"
      >
        <div className="grid grid-cols-2 gap-3">
          <Button
            type="button"
            variant="outline"
            disabled
            className="justify-center"
          >
            Google (coming soon)
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled
            className="justify-center"
          >
            Apple (coming soon)
          </Button>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          or sign up with email
          <span className="h-px flex-1 bg-border" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Input
            label="First name"
            autoComplete="given-name"
            value={values.firstName}
            onChange={(event) => handleChange("firstName", event.target.value)}
            onBlur={() => handleBlur("firstName")}
            error={touched.firstName ? errors.firstName : undefined}
          />
          <Input
            label="Last name"
            autoComplete="family-name"
            value={values.lastName}
            onChange={(event) => handleChange("lastName", event.target.value)}
            onBlur={() => handleBlur("lastName")}
            error={touched.lastName ? errors.lastName : undefined}
          />
        </div>

        <Input
          label="Email"
          type="email"
          autoComplete="email"
          value={values.email}
          onChange={(event) => handleChange("email", event.target.value)}
          onBlur={() => handleBlur("email")}
          error={touched.email ? errors.email : undefined}
          hint={
            touched.email && !errors.email
              ? undefined
              : "Gmail or Outlook addresses only."
          }
        />

        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          value={values.password}
          onChange={(event) => handleChange("password", event.target.value)}
          onBlur={() => handleBlur("password")}
          error={touched.password ? errors.password : undefined}
          hint={
            touched.password && !errors.password
              ? undefined
              : "8+ characters, upper + lowercase, a digit, and a special character."
          }
        />

        <Input
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={values.confirmPassword}
          onChange={(event) =>
            handleChange("confirmPassword", event.target.value)
          }
          onBlur={() => handleBlur("confirmPassword")}
          error={touched.confirmPassword ? errors.confirmPassword : undefined}
        />

        {formError ? <p className="text-sm text-danger">{formError}</p> : null}

        <Button type="submit" size="lg" className="mt-2" loading={isSubmitting}>
          Continue
        </Button>

        <Checkbox
          checked={agreedToTerms}
          onChange={(event) => setAgreedToTerms(event.target.checked)}
          error={agreeError}
          label={
            <>
              I agree to Speeky&apos;s{" "}
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setLegalType("terms");
                }}
                className="font-medium text-primary hover:text-primary-hover focus:outline-none focus:underline"
              >
                Terms &amp; Conditions
              </button>{" "}
              and{" "}
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setLegalType("privacy");
                }}
                className="font-medium text-primary hover:text-primary-hover focus:outline-none focus:underline"
              >
                Privacy Policy
              </button>
              .
            </>
          }
        />
      </form>

      <LegalModal
        open={!!legalType}
        onClose={() => setLegalType(null)}
        type={legalType}
      />
    </>
  );
}