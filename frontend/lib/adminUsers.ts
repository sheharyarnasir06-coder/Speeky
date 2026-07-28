import { api } from "./api";
import type { AuthUser } from "./auth";

export interface UsersPage {
  users: AuthUser[];
  total: number;
  page: number;
  page_size: number;
}

export function listUsers(params: { page?: number; pageSize?: number; role?: string; search?: string } = {}) {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 10));
  if (params.role) query.set("role", params.role);
  if (params.search) query.set("search", params.search);
  return api<UsersPage>(`/users/?${query.toString()}`);
}

export function updateUserRole(userId: string, role: "USER" | "ADMIN") {
  return api<{ user: AuthUser }>(`/users/${userId}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

// Atomically demotes the acting Super Admin to ADMIN and promotes the target —
// ownership only ever moves this way, so there's always exactly one Super Admin.
export function transferSuperAdmin(userId: string) {
  return api<{ user: AuthUser }>(`/users/${userId}/transfer-super-admin`, {
    method: "POST",
  });
}
