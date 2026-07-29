import { api } from "./api";
import type { LearningGoal } from "./goals";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  avatarUrl: string;
  role: string;
  createdAt: string;
  learningGoal: LearningGoal;
  // false for every pre-US-08 account (backfilled) and any account that hasn't
  // submitted a real choice yet — the LearningGoalGate blocks the dashboard on this.
  learningGoalSet: boolean;
  isConsented?: boolean;
  consentVersion?: string | null;
  consentAcceptedAt?: string | null;
}

// Signup is OTP-gated on the backend now: this only sends a code, it does
// NOT create the account or a session — see verifySignupOtp.
export function signup(data: { name: string; email: string; password: string }) {
  return api<{ message: string }>("/auth/signup", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function verifySignupOtp(data: { email: string; code: string }) {
  return api<{ user: AuthUser }>("/auth/signup/verify-otp", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function resendSignupOtp(email: string) {
  return api<{ message: string }>("/auth/signup/resend-otp", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function login(data: {
  email: string;
  password: string;
}) {
  return api<{ user: AuthUser }>("/auth/login", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function logout() {
  return api("/auth/logout", {
    method: "POST",
  });
}

export function getCurrentUser() {
  return api<{ user: AuthUser }>("/users/me");
}

export function forgotPassword(email: string) {
  return api("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function resetPassword(token: string, password: string) {
  return api("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({
      token,
      password,
    }),
  });
}
