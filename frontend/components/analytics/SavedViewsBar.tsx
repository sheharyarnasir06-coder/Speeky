"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { AlertTriangle, Bookmark, Check, Trash2, Plus, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Badge } from "@/components/ui/badge";
import {
  createSavedView,
  deleteSavedView,
  getSavedViews,
  type SavedViewResponse,
  type DashboardWidgetConfig,
} from "@/lib/analytics";
import { ApiError } from "@/lib/api";

interface SavedViewsBarProps {
  currentFilters: Record<string, unknown>;
  currentWidgets: DashboardWidgetConfig[];
  activeView: SavedViewResponse | null;
  onApplyView: (view: SavedViewResponse | null) => void;
  onRemoveDeprecatedWidget?: (widgetId: string) => void;
}

export function SavedViewsBar({
  currentFilters,
  currentWidgets,
  activeView,
  onApplyView,
  onRemoveDeprecatedWidget,
}: SavedViewsBarProps) {
  const [views, setViews] = React.useState<SavedViewResponse[]>([]);
  const [loading, setLoading] = React.useState(true);

  // Modal states
  const [isSaveModalOpen, setIsSaveModalOpen] = React.useState(false);
  const [viewName, setViewName] = React.useState("");
  const [isShared, setIsShared] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [showOverwriteConfirm, setShowOverwriteConfirm] = React.useState(false);

  // Delete states
  const [deletingId, setDeletingId] = React.useState<string | null>(null);

  const loadViews = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSavedViews();
      setViews(res.views || []);
    } catch {
      // Toast optional on initial load fail
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadViews();
  }, [loadViews]);

  async function handleSave(overwrite = false) {
    if (!viewName.trim()) {
      toast.error("Please enter a name for the view.");
      return;
    }

    const collision = views.find((v) => v.name.toLowerCase() === viewName.trim().toLowerCase());
    if (collision && !overwrite && !showOverwriteConfirm) {
      setShowOverwriteConfirm(true);
      return;
    }

    setSaving(true);
    try {
      const saved = await createSavedView({
        name: viewName.trim(),
        widgets: currentWidgets,
        filters: currentFilters,
        is_shared: isShared,
        overwrite,
      });

      toast.success(overwrite ? `View "${saved.name}" updated!` : `View "${saved.name}" saved!`);
      setIsSaveModalOpen(false);
      setShowOverwriteConfirm(false);
      setViewName("");
      setIsShared(false);
      await loadViews();
      onApplyView(saved);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setShowOverwriteConfirm(true);
      } else {
        toast.error(err instanceof ApiError ? err.message : "Failed to save view.");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(viewId: string, e: React.MouseEvent) {
    e.stopPropagation();
    setDeletingId(viewId);
    try {
      await deleteSavedView(viewId);
      toast.success("Saved view deleted.");
      if (activeView?.id === viewId) {
        onApplyView(null);
      }
      await loadViews();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete view.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface-elevated p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bookmark className="h-4 w-4 text-primary" aria-hidden="true" />
          <span className="text-sm font-semibold text-foreground">Saved Dashboard Views</span>
          {activeView ? (
            <Badge tone="brand" className="text-xs">
              Active: {activeView.name}
            </Badge>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          {activeView ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onApplyView(null)}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Reset to Default Layout
            </Button>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setViewName("");
              setIsShared(false);
              setShowOverwriteConfirm(false);
              setIsSaveModalOpen(true);
            }}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Save Current View
          </Button>
        </div>
      </div>

      {/* Views chips / selector */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {loading ? (
          <span className="text-xs text-muted-foreground">Loading saved views…</span>
        ) : views.length === 0 ? (
          <span className="text-xs text-muted-foreground">
            No saved views yet. Customize layout & filters and click &quot;Save Current View&quot;.
          </span>
        ) : (
          views.map((view) => {
            const isActive = activeView?.id === view.id;
            return (
              <div
                key={view.id}
                onClick={() => onApplyView(view)}
                className={`group flex cursor-pointer items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors ${
                  isActive
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-surface text-muted-foreground hover:border-muted-foreground hover:text-foreground"
                }`}
              >
                <span>{view.name}</span>
                {view.is_shared ? (
                  <span title="Shared View">
                    <Share2 className="h-3 w-3 opacity-60" aria-hidden="true" />
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={(e) => handleDelete(view.id, e)}
                  disabled={deletingId === view.id}
                  className="opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                  title="Delete view"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Inline warnings from active view if backend reported segment fallback or missing widget */}
      {activeView && activeView.warnings && activeView.warnings.length > 0 ? (
        <div className="mt-1 flex flex-col gap-1 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-foreground">
          {activeView.warnings.map((warn, i) => (
            <div key={i} className="flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
              <span>{warn}</span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Save View Modal */}
      <Modal
        open={isSaveModalOpen}
        onClose={() => setIsSaveModalOpen(false)}
        title={showOverwriteConfirm ? "Overwrite Existing View?" : "Save Custom View"}
      >
        {showOverwriteConfirm ? (
          <div className="flex flex-col gap-4 text-sm">
            <div className="flex items-center gap-3 rounded-xl border border-warning bg-warning/10 p-3 text-foreground">
              <AlertTriangle className="h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
              <p>
                A view named <strong className="font-semibold">{viewName}</strong> already exists. Overwriting will update its layout and filters for all users it is shared with.
              </p>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="outline" onClick={() => setShowOverwriteConfirm(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={() => handleSave(true)}>
                Overwrite View
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <Input
              label="View Name"
              placeholder="e.g., Q3 Retention & Growth"
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
              autoFocus
            />

            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={isShared}
                onChange={(e) => setIsShared(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Share this view with other admins (Role-restricted widgets will be automatically hidden for lower-permission roles)
            </label>

            <div className="flex justify-end gap-3 pt-3">
              <Button variant="outline" onClick={() => setIsSaveModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={() => handleSave(false)}>
                Save View
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
