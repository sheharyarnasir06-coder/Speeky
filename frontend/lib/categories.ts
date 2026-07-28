import { api } from "./api";

export interface Category {
  id: string;
  name: string;
  slug: string;
  icon: string;
  order: number;
  protected: boolean;
  scenario_count: number;
}

export interface CategoryInput {
  name: string;
  icon: string;
  order?: number;
}

// Learner-facing — only categories with at least one active scenario (CM-US-05 E-01).
export function listCategories() {
  return api<{ categories: Category[] }>("/categories/");
}

// Admin — full taxonomy, including empty categories awaiting content.
export function adminListCategories() {
  return api<{ categories: Category[] }>("/categories/admin");
}

export function adminCreateCategory(data: CategoryInput) {
  return api<Category>("/categories/admin", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function adminUpdateCategory(id: string, data: CategoryInput) {
  return api<Category>(`/categories/admin/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function adminDeleteCategory(id: string) {
  return api<{ deleted: boolean }>(`/categories/admin/${id}`, {
    method: "DELETE",
  });
}
