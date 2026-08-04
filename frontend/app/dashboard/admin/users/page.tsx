"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Crown, Search, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/ui/pagination";
import { ApiError } from "@/lib/api";
import { listUsers, transferSuperAdmin, updateUserRole, type UsersPage } from "@/lib/adminUsers";
import { useAuth } from "@/contexts/AuthContext";

const PAGE_SIZE = 10;

const ROLE_FILTERS = [
  { value: "", label: "All roles" },
  { value: "USER", label: "Learner" },
  { value: "ADMIN", label: "Admin" },
  { value: "SUPER_ADMIN", label: "Super Admin" },
];

// "brand" is the Badge tone for the primary brand colour — an earlier revision of
// this file called it "primary", which is not a tone the component accepts.
const ROLE_TONE: Record<string, "brand" | "neutral" | "warning"> = {
  SUPER_ADMIN: "warning",
  ADMIN: "brand",
  USER: "neutral",
};

export default function AdminUsersPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [data, setData] = React.useState<UsersPage | null>(null);
  const [page, setPage] = React.useState(1);
  const [role, setRole] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const isSuperAdmin = user?.role === "SUPER_ADMIN";

  const refresh = React.useCallback(() => {
    listUsers({ page, pageSize: PAGE_SIZE, role: role || undefined, search: search || undefined })
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load users."));
  }, [page, role, search]);

  React.useEffect(() => {
    if (isSuperAdmin) refresh();
  }, [isSuperAdmin, refresh]);

  React.useEffect(() => {
    setPage(1);
  }, [role, search]);

  async function handlePromote(targetId: string) {
    setBusyId(targetId);
    try {
      await updateUserRole(targetId, "ADMIN");
      refresh();
      toast.success("Promoted to Admin.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't promote this account.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRevoke(targetId: string) {
    setBusyId(targetId);
    try {
      await updateUserRole(targetId, "USER");
      refresh();
      toast.success("Admin access revoked.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't revoke this account.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleTransfer(targetId: string, targetName: string) {
    if (
      !window.confirm(
        `Make "${targetName}" the Super Admin? You will be demoted to Admin immediately — this account can only be Super Admin one at a time.`,
      )
    )
      return;
    setBusyId(targetId);
    try {
      await transferSuperAdmin(targetId);
      refresh();
      toast.success(`${targetName} is now the Super Admin.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't transfer Super Admin.");
    } finally {
      setBusyId(null);
    }
  }

  if (authLoading) return null;

  if (!isSuperAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Super Admin access required.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Manage Users
        </h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Every learner and admin account. Promote to Admin, revoke Admin access, or transfer
          Super Admin ownership — only one account holds it at a time.
        </p>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or email..."
            className="h-11 w-full rounded-xl border border-input bg-surface pl-11 pr-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
        </div>
        <div className="w-full sm:w-48">
          <Select
            label="Role"
            hideLabel
            value={role}
            onChange={(e) => setRole(e.target.value)}
            options={ROLE_FILTERS}
          />
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface-elevated">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Joined</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(data?.users ?? []).map((u) => {
              const isSelf = u.id === user?.id;
              const busy = busyId === u.id;
              return (
                <tr key={u.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-medium text-foreground">
                    {u.name}
                    {isSelf ? <span className="ml-1.5 text-xs text-muted-foreground">(you)</span> : null}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                  <td className="px-4 py-3">
                    <Badge tone={ROLE_TONE[u.role] ?? "neutral"}>{u.role}</Badge>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {new Date(u.createdAt).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      {u.role === "USER" ? (
                        <Button size="sm" variant="outline" loading={busy} onClick={() => handlePromote(u.id)}>
                          Promote to Admin
                        </Button>
                      ) : null}
                      {u.role === "ADMIN" ? (
                        <>
                          <Button size="sm" variant="outline" loading={busy} onClick={() => handleRevoke(u.id)}>
                            Revoke Admin
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={busy}
                            onClick={() => handleTransfer(u.id, u.name)}
                          >
                            <Crown className="h-4 w-4" aria-hidden="true" />
                            Make Super Admin
                          </Button>
                        </>
                      ) : null}
                      {u.role === "SUPER_ADMIN" && !isSelf ? (
                        <span className="text-xs text-muted-foreground">Current Super Admin</span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
            {data && data.users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  No users match this filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {data ? (
        <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
      ) : null}
    </div>
  );
}
