"use client";

import { Slide, ToastContainer } from "react-toastify";
import { AuthProvider } from "@/contexts/AuthContext";
import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";

function AppProviders({ children }: { children: React.ReactNode }) {
  const { theme } = useTheme();
  return (
    <>
      <AuthProvider>{children}</AuthProvider>
      <ToastContainer
        position="bottom-right"
        autoClose={2500}
        newestOnTop
        closeOnClick
        limit={3}
        pauseOnHover={false}
        theme={theme === "dark" ? "dark" : "light"}
        transition={Slide}
      />
    </>
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AppProviders>{children}</AppProviders>
    </ThemeProvider>
  );
}
