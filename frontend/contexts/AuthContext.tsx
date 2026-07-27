"use client";

import * as React from "react";
import {
  getCurrentUser,
  logout as logoutRequest,
  type AuthUser,
} from "@/lib/auth";
import { toast } from "react-toastify";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  setUser: (user: AuthUser | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | undefined>(
  undefined,
);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);

  React.useEffect(() => {
    getCurrentUser()
      .then((data) => setUser(data.user))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  // lib/api.ts fires this when a 401 survives a refresh attempt (refresh
  // token itself expired/revoked) — clear state so dashboard guards send
  // the user back to /login instead of leaving stale "logged in" UI up
  // while every API call silently fails.

  // This worked with [] also due to stale-closures. (React gurantees recent-state)
  // setUser((currentUser) => {
  //       if (currentUser)
  //         toast.info("Your session has expired. Please log in again.");
  //       return null;
  //     });
  React.useEffect(() => {
    function handleSessionExpired() {
      if (user) toast.info("Your session has expired. Please log in again.");
      setUser(null);
    }
    window.addEventListener("speeky:session-expired", handleSessionExpired);

    return () =>
      window.removeEventListener(
        "speeky:session-expired",
        handleSessionExpired,
      );
  }, [user]);

  const logout = React.useCallback(async () => {
    try {
      await logoutRequest();
      toast.success("Logged out successfully");
    } catch {
      // Session may already be invalid server-side — clear it client-side regardless.
    }
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, setUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
