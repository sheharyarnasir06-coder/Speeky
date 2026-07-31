"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, BarChart3, FolderTree, ShieldAlert, FileText, Users2, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";

interface AdminHubCard {
  href: string;
  icon: typeof Wand2;
  title: string;
  description: string;
  superAdminOnly?: boolean;
  complianceOnly?: boolean;
}

const CARDS: AdminHubCard[] = [
  {
    href: "/dashboard/admin/scenarios",
    icon: Wand2,
    title: "Custom Scenarios",
    description:
      "Author Scenario-Based Learning templates: prompt, persona, vocabulary, difficulty — test in the sandbox, evaluate quality and confidence, and manage versions.",
  },
  {
    href: "/dashboard/admin/categories",
    icon: FolderTree,
    title: "Categories",
    description:
      "Manage the scenario category taxonomy learners browse by — add new categories, move scenarios between them, retire unused ones.",
  },
  {
    href: "/dashboard/admin/analytics",
    icon: BarChart3,
    title: "Analytics",
    description:
      "Active users, retention, onboarding drop-off, and feature adoption. Super Admins also see platform revenue.",
  },
  {
    href: "/dashboard/admin/audit-logs",
    icon: FileText,
    title: "Audit Log Trail",
    description:
      "Inspect tamper-evident action logs, filter export events, and verify hash chain integrity.",
    complianceOnly: true,
  },
  {
    href: "/dashboard/admin/users",
    icon: Users2,
    title: "Manage Users",
    description:
      "View every learner and admin account, promote or revoke Admin access, and transfer Super Admin ownership.",
    superAdminOnly: true,
  },
];

export default function AdminHubPage() {
  const { user, isLoading } = useAuth();

  if (isLoading) return null;

  const role = user?.role ?? "";
  const canAccessAdmin = role === "ADMIN" || role === "SUPER_ADMIN" || role === "COMPLIANCE" || role === "FINANCE";
  if (!canAccessAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Admin access required.</p>
      </div>
    );
  }

  const isSuperAdmin = role === "SUPER_ADMIN";
  const isComplianceOrSuper = role === "COMPLIANCE" || role === "SUPER_ADMIN";

  const cards = CARDS.filter((c) => {
    if (c.superAdminOnly && !isSuperAdmin) return false;
    if (c.complianceOnly && !isComplianceOrSuper) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Admin Hub
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          {isSuperAdmin
            ? "Everything an Admin can do, plus user management and financial reconciliation."
            : "Content, analytics, and administrative management tools."}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <Link
              key={card.href}
              href={card.href}
              className={cn(
                "group flex h-full flex-col justify-between rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:shadow-md",
              )}
            >
              <div>
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary transition-transform duration-300 group-hover:scale-110">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <h3 className="mt-4 font-serif text-lg font-semibold text-foreground">
                  {card.title}
                </h3>
                <p className="mt-2 text-sm text-muted-foreground">{card.description}</p>
              </div>
              <div className="mt-6 flex items-center gap-2 text-sm font-medium text-primary">
                Open
                <ArrowRight
                  className="h-4 w-4 transition-transform group-hover:translate-x-1"
                  aria-hidden="true"
                />
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
