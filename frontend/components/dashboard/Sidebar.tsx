"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { ClipboardList, ShieldCheck, Crown, FileText } from "lucide-react";
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

export function Sidebar() {
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

  return (
    <aside className="flex w-[4.5rem] shrink-0 flex-col items-center border-r border-border bg-surface-elevated px-2 py-6 lg:w-64 lg:items-stretch lg:px-4">
      <div className="flex flex-col items-center px-2 lg:items-start">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Image
            src="/logo-icon.png"
            alt="Speeky"
            width={28}
            height={28}
            className="h-7 w-7 transition-all dark:brightness-0 dark:invert"
          />
          <span className="hidden font-serif text-h2 font-semibold tracking-tight text-primary dark:text-white lg:block">
            Speeky
          </span>
        </Link>
        <p className="hidden pl-9 text-xs font-medium tracking-wide text-muted-foreground lg:block">
          AI COACH
        </p>
      </div>

      <nav
        aria-label="Dashboard"
        className="mt-8 flex w-full flex-col items-center gap-1 lg:items-stretch"
      >
        {DASHBOARD_NAV_LINKS.map((link) => {
          const isActive = pathname === link.href;
          const Icon = link.icon;
          const hasResumable = RESUMABLE_HREFS[link.href];
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-label={hasResumable ? `${link.label} — unfinished session to resume` : link.label}
              title={hasResumable ? `${link.label} — unfinished session to resume` : link.label}
              className={cn(
                "relative flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors lg:justify-start",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-surface hover:text-foreground",
              )}
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
              <span className="hidden lg:inline">{link.label}</span>
            </Link>
          );
        })}
        {showAssessmentLink ? (
          <Link
            href="/dashboard/assessment"
            aria-label="Baseline Assessment"
            title="Baseline Assessment"
            className={cn(
              "flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors lg:justify-start",
              pathname === "/dashboard/assessment"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface hover:text-foreground",
            )}
          >
            <ClipboardList className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="hidden lg:inline">Assessment</span>
          </Link>
        ) : null}
        {isAdminRole ? (
          <Link
            href="/dashboard/admin"
            aria-label="Admin"
            title="Admin"
            className={cn(
              "flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors lg:justify-start",
              pathname.startsWith("/dashboard/admin") && pathname !== "/dashboard/admin/users" && pathname !== "/dashboard/admin/audit-logs"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface hover:text-foreground",
            )}
          >
            <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="hidden lg:inline">Admin</span>
          </Link>
        ) : null}
        {isComplianceOrSuper ? (
          <Link
            href="/dashboard/admin/audit-logs"
            aria-label="Audit Logs"
            title="Audit Logs"
            className={cn(
              "flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors lg:justify-start",
              pathname === "/dashboard/admin/audit-logs"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface hover:text-foreground",
            )}
          >
            <FileText className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="hidden lg:inline">Audit Logs</span>
          </Link>
        ) : null}
        {user?.role === "SUPER_ADMIN" ? (
          <Link
            href="/dashboard/admin/users"
            aria-label="Super Admin: Manage Users"
            title="Super Admin: Manage Users"
            className={cn(
              "flex items-center justify-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors lg:justify-start",
              pathname === "/dashboard/admin/users"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-surface hover:text-foreground",
            )}
          >
            <Crown className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="hidden lg:inline">Super Admin</span>
          </Link>
        ) : null}
      </nav>

      {user ? (
        <Link
          href="/dashboard/profile"
          aria-label={`View profile — ${user.name}`}
          title={user.name}
          className="mt-auto flex w-full items-center justify-center gap-3 rounded-xl border-t border-border px-2 pt-4 transition-colors hover:text-primary lg:justify-start"
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
          <span className="hidden min-w-0 flex-col lg:flex">
            <span className="truncate text-sm font-medium text-foreground">
              {user.name}
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {ROLE_LABELS[user.role] ?? user.role}
            </span>
          </span>
        </Link>
      ) : null}
    </aside>
  );
}
