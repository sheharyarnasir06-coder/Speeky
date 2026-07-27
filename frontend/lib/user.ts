import { api } from "./api";
import type { AuthUser } from "./auth";

export function updateProfile(data: { name: string }) {
  return api<{ user: AuthUser }>("/users/me", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// Email changes are OTP-gated: request sends a code to the NEW address (also
// used to resend — it just regenerates the code), verify applies it.
export function requestEmailChange(email: string) {
  return api<{ message: string }>("/users/me/email/request-change", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyEmailChange(code: string) {
  return api<{ user: AuthUser }>("/users/me/email/verify-change", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export function uploadAvatar(file: File) {
  const formData = new FormData();
  formData.append("avatar", file);
  return api<{ user: AuthUser }>("/users/me/avatar", {
    method: "PATCH",
    body: formData,
  });
}

export function deleteAccount(password: string) {
  return api<null>("/users/me", {
    method: "DELETE",
    body: JSON.stringify({ password }),
  });
}
