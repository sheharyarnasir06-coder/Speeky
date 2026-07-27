"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "react-toastify";
import { Trash2, TriangleAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api";
import { deleteAccount } from "@/lib/user";
import { useAuth } from "@/contexts/AuthContext";

/**
 * US-07: Account Deletion — wired to the real DELETE /users/me endpoint.
 * Typing the account's own email is a "type to confirm" safety gate before
 * the real confirmation (email + password) unlocks inside the popup —
 * password stays required since the backend's DeleteAccountSchema requires
 * it regardless.
 */
export function DangerZoneSection() {
  const { user, setUser } = useAuth();
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [emailConfirm, setEmailConfirm] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [isDeleting, setIsDeleting] = React.useState(false);

  if (!user) return null;

  const emailMatches =
    emailConfirm.trim().toLowerCase() === user.email.toLowerCase();

  function closeModal() {
    setOpen(false);
    setEmailConfirm("");
    setPassword("");
    setError(null);
  }

  async function handleDelete() {
    if (!emailMatches) {
      setError("That email doesn't match your account.");
      return;
    }
    if (!password) {
      setError("Enter your password to confirm.");
      return;
    }
    setError(null);
    setIsDeleting(true);
    try {
      await deleteAccount(password);
      setUser(null);
      toast.success("Account deleted.");
      router.push("/");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setError(message);
      toast.error(message);
      setIsDeleting(false);
    }
  }

  return (
    <div className="rounded-2xl border border-danger/30 bg-danger/5 p-6 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-danger/10 text-danger">
          <Trash2 className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Danger Zone</h2>
          <p className="text-sm text-muted-foreground">
            Permanently delete your account and all associated data. This
            can&apos;t be undone.
          </p>
        </div>
      </div>

      <Button
        type="button"
        variant="danger"
        size="sm"
        className="mt-4"
        onClick={() => setOpen(true)}
      >
        Delete Account
      </Button>

      <Modal
        open={open}
        onClose={isDeleting ? () => {} : closeModal}
        title="Delete your account?"
        description="This permanently removes your profile, progress, and practice history. This can't be undone."
      >
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-2.5 rounded-xl bg-danger/10 px-3 py-2.5 text-xs text-danger">
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            To confirm, type your email address below.
          </div>

          <Input
            label={`Type "${user.email}" to confirm`}
            value={emailConfirm}
            onChange={(event) => setEmailConfirm(event.target.value)}
            autoComplete="off"
          />

          {emailMatches ? (
            <Input
              label="Password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          ) : null}

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="danger"
              size="sm"
              loading={isDeleting}
              disabled={!emailMatches}
              onClick={handleDelete}
            >
              Permanently Delete
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isDeleting}
              onClick={closeModal}
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
