"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { ClipboardList, ShieldCheck, Crown, FileText, X } from "lucide-react";
import { cn, getInitials } from "@/lib/utils";
import { DASHBOARD_NAV_LINKS } from "@/lib/dashboard-data";
import { useAuth } from "@/contexts/AuthContext";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";
import { useActiveSessions } from "@/contexts/ActiveSessionsContext";
import { API_ORIGIN } from "@/lib/api";

const ROLE_LABELS: Record<string, string> = {
  SUPER_ADMIN: "Super Admin",
  ADMIN: "Administrator",
  COMPLIANCE: "Compliance Officer",
  FINANCE: "Finance Admin",
  USER: "Learner",
};

interface SidebarProps {
  // Below `lg` the full <aside> is hidden entirely. So this drives
  // the slide-in drawer that replaces it instead. Owned by DashboardLayout
  // since the hamburger button that opens it lives in the shared header.
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  const pathname = usePathname();
  const { user } = useAuth();
  const { access } = useAssessmentAccess();
  const { explore, publicSpeaking, pronunciation } = useActiveSessions();

  const RESUMABLE_HREFS: Record<string, boolean> = {
    "/dashboard/explore": Boolean(explore?.active),
    "/dashboard/pronunciation": Boolean(pronunciation?.found),
    "/dashboard/public-speaking": Boolean(publicSpeaking?.found),
  };

  const showAssessmentLink =
    access != null &&
    access.assessment_status !== "COMPLETED" &&
    access.assessment_status !== "PLATEAUED";

  const isAdminRole = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN" || user?.role === "COMPLIANCE" || user?.role === "FINANCE";
  const isComplianceOrSuper = user?.role === "COMPLIANCE" || user?.role === "SUPER_ADMIN";

  // Shared between the desktop rail and the mobile drawer so the link list is
  // never maintained twice. `expanded` swaps the icon-only rail styling for
  // full labels (the drawer is always wide enough to show them).
  function NavLinks({ expanded, onNavigate }: { expanded: boolean; onNavigate?: () => void }) {
    const itemClass = (active: boolean) =>
      cn(
        "relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
        expanded ? "justify-start" : "justify-center lg:justify-start",
        active
          ? "bg-gradient-to-r from-primary to-primary/80 text-primary-foreground shadow-[0_10px_28px_hsl(var(--primary)/0.22)]"
          : "text-muted-foreground hover:bg-surface hover:text-foreground",
      );
    const labelClass = expanded ? "inline" : "hidden lg:inline";

    return (
      <nav
        aria-label="Dashboard"
        className={cn("mt-8 flex w-full flex-col gap-1", expanded ? "items-stretch" : "items-center lg:items-stretch")}
      >
        {DASHBOARD_NAV_LINKS.map((link) => {
          const isActive = pathname === link.href;
          const Icon = link.icon;
          const hasResumable = RESUMABLE_HREFS[link.href];
          return (
            <Link
              key={link.href}
              href={link.href}
              onClick={onNavigate}
              aria-label={hasResumable ? `${link.label} — unfinished session to resume` : link.label}
              title={hasResumable ? `${link.label} — unfinished session to resume` : link.label}
              className={itemClass(isActive)}
            >
              <span className="relative shrink-0">
                <Icon className="h-4 w-4" aria-hidden="true" />
                {hasResumable ? (
                  <span
                    className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-warning"
                    aria-hidden="true"
                  />
                ) : null}
              </span>
              <span className={labelClass}>{link.label}</span>
            </Link>
          );
        })}
        {showAssessmentLink ? (
          <Link
            href="/dashboard/assessment"
            onClick={onNavigate}
            aria-label="Baseline Assessment"
            title="Baseline Assessment"
            className={itemClass(pathname === "/dashboard/assessment")}
          >
            <ClipboardList className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className={labelClass}>Assessment</span>
          </Link>
        ) : null}
        {isAdminRole ? (
          <Link
            href="/dashboard/admin"
            onClick={onNavigate}
            aria-label="Admin"
            title="Admin"
            className={itemClass(
              pathname.startsWith("/dashboard/admin") && pathname !== "/dashboard/admin/users" && pathname !== "/dashboard/admin/audit-logs",
            )}
          >
            <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className={labelClass}>Admin</span>
          </Link>
        ) : null}
        {isComplianceOrSuper ? (
          <Link
            href="/dashboard/admin/audit-logs"
            onClick={onNavigate}
            aria-label="Audit Logs"
            title="Audit Logs"
            className={itemClass(pathname === "/dashboard/admin/audit-logs")}
          >
            <FileText className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className={labelClass}>Audit Logs</span>
          </Link>
        ) : null}
        {user?.role === "SUPER_ADMIN" ? (
          <Link
            href="/dashboard/admin/users"
            onClick={onNavigate}
            aria-label="Super Admin: Manage Users"
            title="Super Admin: Manage Users"
            className={itemClass(pathname === "/dashboard/admin/users")}
          >
            <Crown className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className={labelClass}>Super Admin</span>
          </Link>
        ) : null}
      </nav>
    );
  }

  function ProfileLink({ expanded, onNavigate }: { expanded: boolean; onNavigate?: () => void }) {
    if (!user) return null;
    return (
      <Link
        href="/dashboard/profile"
        onClick={onNavigate}
        aria-label={`View profile — ${user.name}`}
        title={user.name}
        className={cn(
          "mt-auto flex w-full items-center gap-3 rounded-xl border-t border-border px-2 pt-4 transition-colors hover:text-primary",
          expanded ? "justify-start" : "justify-center lg:justify-start",
        )}
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full bg-secondary text-sm font-semibold text-primary">
          {user.avatarUrl && user.avatarUrl !== "user.webp" ? (
            <Image
              src={`${API_ORIGIN}/uploads/avatars/${user.avatarUrl}`}
              alt=""
              width={40}
              height={40}
              className="h-full w-full object-cover"
              unoptimized
            />
          ) : (
            getInitials(user.name)
          )}
        </span>
        <span className={cn("min-w-0 flex-col", expanded ? "flex" : "hidden lg:flex")}>
          <span className="truncate text-sm font-medium text-foreground">
            {user.name}
          </span>
          <span className="truncate text-xs text-muted-foreground">
            {ROLE_LABELS[user.role] ?? user.role}
          </span>
        </span>
      </Link>
    );
  }

  return (
    <>
      {/* Desktop / tablet rail — icon-only below `lg`, labeled at `lg+`. Hidden
          entirely below that, replaced by the drawer below. */}
      <aside key={pathname} className="hidden w-[4.5rem] shrink-0 flex-col items-center border-r border-border bg-[linear-gradient(180deg,hsl(var(--surface-elevated)),hsl(var(--surface))),radial-gradient(90%_28%_at_0%_0%,hsl(var(--primary)/0.12),transparent_60%),radial-gradient(70%_24%_at_100%_100%,hsl(var(--accent)/0.08),transparent_60%)] px-2 py-6 lg:flex lg:w-64 lg:items-stretch lg:px-4 animate-scale-in">
        <div className="flex flex-col items-center px-2 lg:items-start">
          <Link href="/dashboard" className="flex items-center gap-2">
            <Image
              src="/speeky-consolidated-logo.png"
              alt="Speeky powered by Mazik Global"
              width={277}
              height={100}
              className="speeky-logo-heartbeat h-12 w-auto max-w-[13rem] transition-all dark:brightness-0 dark:invert"
            />
          </Link>
        </div>
        <NavLinks expanded={false} />
        <ProfileLink expanded={false} />
      </aside>

      {/* Mobile / tablet drawer — triggered by the hamburger button in the
          shared header (DashboardLayout owns the open state). */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 animate-fade-in bg-foreground/40"
            onClick={onMobileClose}
          />
          <aside className="relative flex h-full w-72 max-w-[80vw] animate-slide-in-left flex-col overflow-y-auto border-r border-border bg-[linear-gradient(180deg,hsl(var(--surface-elevated)),hsl(var(--surface))),radial-gradient(90%_28%_at_0%_0%,hsl(var(--primary)/0.12),transparent_60%),radial-gradient(70%_24%_at_100%_100%,hsl(var(--accent)/0.08),transparent_60%)] px-4 py-6 shadow-xl">
            <div className="flex items-center justify-between">
              <Link href="/dashboard" className="flex items-center gap-2" onClick={onMobileClose}>
                <Image
                  src="/speeky-consolidated-logo.png"
                  alt="Speeky powered by Mazik Global"
                  width={277}
                  height={100}
                  className="speeky-logo-heartbeat h-12 w-auto max-w-[13rem] dark:brightness-0 dark:invert"
                />
              </Link>
              <button
                type="button"
                aria-label="Close menu"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-surface hover:text-foreground"
                onClick={onMobileClose}
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <NavLinks expanded onNavigate={onMobileClose} />
            <ProfileLink expanded onNavigate={onMobileClose} />
          </aside>
        </div>
      ) : null}
    </>
  );
}
