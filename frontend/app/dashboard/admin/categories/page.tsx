"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { Lock, Pencil, Plus, ShieldAlert, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Modal } from "@/components/ui/modal";
import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api";
import {
  adminCreateCategory,
  adminDeleteCategory,
  adminListCategories,
  adminUpdateCategory,
  type Category,
  type CategoryInput,
} from "@/lib/categories";
import { ICON_NAMES, resolveIcon } from "@/lib/icon-map";
import { useAuth } from "@/contexts/AuthContext";

const EMPTY_FORM: CategoryInput = { name: "", icon: "folder", order: 0 };

const ICON_OPTIONS = ICON_NAMES.map((name) => ({ value: name, label: name }));

export default function AdminCategoriesPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [categories, setCategories] = React.useState<Category[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [modalOpen, setModalOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [form, setForm] = React.useState<CategoryInput>(EMPTY_FORM);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  const refresh = React.useCallback(() => {
    adminListCategories()
      .then((data) => setCategories(data.categories))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load categories."),
      );
  }, []);

  React.useEffect(() => {
    if (isAdmin) refresh();
  }, [isAdmin, refresh]);

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setModalOpen(true);
  }

  function openEdit(category: Category) {
    setEditingId(category.id);
    setForm({ name: category.name, icon: category.icon, order: category.order });
    setFormError(null);
    setModalOpen(true);
  }

  async function handleSave() {
    setFormError(null);
    if (form.name.trim().length < 2) {
      setFormError("Category name must be at least 2 characters.");
      return;
    }
    setSaving(true);
    try {
      if (editingId) {
        await adminUpdateCategory(editingId, form);
      } else {
        await adminCreateCategory(form);
      }
      setModalOpen(false);
      refresh();
      toast.success(editingId ? "Category updated." : "Category created.");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't save this category.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(category: Category) {
    if (!window.confirm(`Delete "${category.name}"? This cannot be undone.`)) return;
    try {
      await adminDeleteCategory(category.id);
      refresh();
      toast.success("Category deleted.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't delete this category.");
    }
  }

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 rounded-2xl border border-danger/30 bg-danger/5 p-8 text-center">
        <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
        <p className="text-sm text-foreground">Admin access required.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
            Categories
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            The taxonomy learners browse scenarios by. New categories appear on the Explore
            page automatically once they have at least one scenario — no app update needed.
          </p>
        </div>
        <Button size="md" onClick={openCreate}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          New Category
        </Button>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(categories ?? []).map((category) => {
          const Icon = resolveIcon(category.icon);
          return (
            <div
              key={category.id}
              className="flex flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm"
            >
              <div className="flex items-start justify-between">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => openEdit(category)}
                    aria-label={`Edit ${category.name}`}
                    className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface hover:text-foreground"
                  >
                    <Pencil className="h-4 w-4" aria-hidden="true" />
                  </button>
                  {!category.protected ? (
                    <button
                      type="button"
                      onClick={() => handleDelete(category)}
                      aria-label={`Delete ${category.name}`}
                      className="rounded-lg p-1.5 text-muted-foreground hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              </div>
              <div>
                <h3 className="flex items-center gap-1.5 font-serif text-lg font-semibold text-foreground">
                  {category.name}
                  {category.protected ? (
                    <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                  ) : null}
                </h3>
                <div className="mt-2 flex items-center gap-2">
                  <Badge tone={category.scenario_count > 0 ? "success" : "neutral"}>
                    {category.scenario_count} scenario{category.scenario_count === 1 ? "" : "s"}
                  </Badge>
                  {category.scenario_count === 0 ? (
                    <span className="text-xs text-muted-foreground">Hidden from learners</span>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
        {categories && categories.length === 0 ? (
          <p className="text-sm text-muted-foreground">No categories yet.</p>
        ) : null}
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingId ? "Edit Category" : "New Category"}
        className="max-w-md"
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Name"
            value={form.name}
            disabled={Boolean(editingId && categories?.find((c) => c.id === editingId)?.protected)}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Select
            label="Icon"
            value={form.icon}
            onChange={(e) => setForm({ ...form, icon: e.target.value })}
            options={ICON_OPTIONS}
          />
          {formError ? <p className="text-sm text-danger">{formError}</p> : null}
          <Button size="lg" loading={saving} onClick={handleSave}>
            {editingId ? "Save Changes" : "Create Category"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
