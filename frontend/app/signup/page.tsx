import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { SignupForm } from "@/components/auth/SignupForm";

export const metadata: Metadata = {
  title: "Sign Up — Speeky",
  description: "Create your Speeky account.",
};

export default function SignupPage() {
  return (
    <AuthShell
      eyebrow="Get started"
      title="Create your account"
      description="Start practicing real conversations, interviews, and workplace scenarios with an AI coach."
      footer={
        <p>
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-medium text-primary hover:text-primary-hover"
          >
            Log in
          </Link>
        </p>
      }
      legalNote={
        <p>Start practicing AI-powered conversations in less than a minute.</p>
      }
    >
      <SignupForm />
    </AuthShell>
  );
}
