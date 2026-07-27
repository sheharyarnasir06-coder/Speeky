"use client";

import * as React from "react";
import { toast } from "react-toastify";
import { FlaskConical, Pencil, Plus, ShieldAlert, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api";
import {
  adminCreateCustomScenario,
  adminDeleteCustomScenario,
  adminListCustomScenarios,
  adminUpdateCustomScenario,
  previewCustomScenario,
  type CustomScenario,
  type CustomScenarioInput,
  type ScenarioPreviewTurn,
} from "@/lib/scenario";
import { EXPLORE_CATEGORIES } from "@/lib/dashboard-data";
import { useAuth } from "@/contexts/AuthContext";

const EMPTY_FORM: CustomScenarioInput = {
  title: "",
  category: "Work",
  persona: "",
  intent: "",
  system_prompt: "",
  opening_line: "",
  target_vocab: [],
  goal_type: "roleplay",
  safety_mode: false,
  corporate_tone: true,
};

export default function AdminScenariosPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [scenarios, setScenarios] = React.useState<CustomScenario[] | null>(
    null,
  );
  const [error, setError] = React.useState<string | null>(null);
  const [modalOpen, setModalOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [form, setForm] = React.useState<CustomScenarioInput>(EMPTY_FORM);
  const [vocabText, setVocabText] = React.useState("");
  const [formError, setFormError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [previewOpen, setPreviewOpen] = React.useState(false);
  const [previewTurns, setPreviewTurns] = React.useState<ScenarioPreviewTurn[]>(
    [],
  );
  const [previewInput, setPreviewInput] = React.useState("");
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [previewError, setPreviewError] = React.useState<string | null>(null);

  const isAdmin = user?.role === "ADMIN";

  const refresh = React.useCallback(() => {
    adminListCustomScenarios()
      .then((data) => setScenarios(data.scenarios))
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Couldn't load scenarios.",
        ),
      );
  }, []);

  React.useEffect(() => {
    if (isAdmin) refresh();
  }, [isAdmin, refresh]);

  function resetPreview() {
    setPreviewOpen(false);
    setPreviewTurns([]);
    setPreviewInput("");
    setPreviewError(null);
  }

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setVocabText("");
    setFormError(null);
    resetPreview();
    setModalOpen(true);
  }

  function openEdit(scenario: CustomScenario) {
    setEditingId(scenario.id);
    setForm({
      title: scenario.title,
      category: scenario.category,
      persona: scenario.persona,
      intent: scenario.intent,
      system_prompt: scenario.system_prompt,
      opening_line: scenario.opening_line ?? "",
      target_vocab: scenario.target_vocab,
      goal_type: scenario.goal_type,
      safety_mode: scenario.safety_mode,
      corporate_tone: scenario.corporate_tone,
    });
    setVocabText(scenario.target_vocab.join(", "));
    setFormError(null);
    resetPreview();
    setModalOpen(true);
  }

  async function handleTogglePreview() {
    if (previewOpen) {
      resetPreview();
      return;
    }
    setPreviewOpen(true);
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const targetVocab = vocabText
        .split(",")
        .map((w) => w.trim())
        .filter(Boolean);
      const { reply } = await previewCustomScenario({
        persona: form.persona || "Persona",
        system_prompt: form.system_prompt || "Stay in character.",
        opening_line: form.opening_line,
        target_vocab: targetVocab,
        goal_type: form.goal_type,
        safety_mode: form.safety_mode,
        corporate_tone: form.corporate_tone,
        turns: [],
      });
      setPreviewTurns([{ role: "assistant", content: reply }]);
    } catch (err) {
      setPreviewError(
        err instanceof ApiError ? err.message : "Couldn't start the preview.",
      );
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleSendPreview() {
    if (!previewInput.trim() || previewLoading) return;
    setPreviewError(null);
    const message = previewInput.trim();
    setPreviewInput("");
    const turnsSoFar = previewTurns;
    setPreviewTurns([...turnsSoFar, { role: "user", content: message }]);
    setPreviewLoading(true);
    try {
      const targetVocab = vocabText
        .split(",")
        .map((w) => w.trim())
        .filter(Boolean);
      const { reply } = await previewCustomScenario({
        persona: form.persona || "Persona",
        system_prompt: form.system_prompt || "Stay in character.",
        opening_line: form.opening_line,
        target_vocab: targetVocab,
        goal_type: form.goal_type,
        safety_mode: form.safety_mode,
        corporate_tone: form.corporate_tone,
        turns: turnsSoFar,
        message,
      });
      setPreviewTurns((prev) => [
        ...prev,
        { role: "assistant", content: reply },
      ]);
    } catch (err) {
      setPreviewError(
        err instanceof ApiError ? err.message : "Something went wrong.",
      );
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleSave() {
    setFormError(null);
    const targetVocab = vocabText
      .split(",")
      .map((w) => w.trim())
      .filter(Boolean);
    if (targetVocab.length < 3) {
      setFormError(
        "Add at least 3 target vocabulary words, separated by commas.",
      );
      return;
    }
    if (form.intent.trim().length < 10) {
      setFormError(
        "Add a short learner-facing description (at least 10 characters).",
      );
      return;
    }
    const payload: CustomScenarioInput = { ...form, target_vocab: targetVocab };
    setSaving(true);
    try {
      if (editingId) {
        await adminUpdateCustomScenario(editingId, payload);
      } else {
        await adminCreateCustomScenario(payload);
      }
      setModalOpen(false);
      refresh();
      toast.success(editingId ? "Scenario updated." : "Scenario created.");
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Couldn't save this scenario.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(scenario: CustomScenario) {
    if (!window.confirm(`Delete "${scenario.title}"? This cannot be undone.`))
      return;
    try {
      await adminDeleteCustomScenario(scenario.id);
      refresh();
      toast.success("Scenario deleted.");
    } catch (err) {
      toast.error(
        err instanceof ApiError
          ? err.message
          : "Couldn't delete this scenario.",
      );
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
            Custom Scenarios
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Add or edit Scenario-Based Learning practice scenarios. Changes go
            live for learners immediately — no app update needed.
          </p>
        </div>
        <Button size="md" onClick={openCreate}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          New Scenario
        </Button>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="overflow-hidden rounded-2xl border border-border bg-surface-elevated">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Persona</th>
              <th className="px-4 py-3">Goal type</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(scenarios ?? []).map((scenario) => (
              <tr
                key={scenario.id}
                className="border-b border-border last:border-0"
              >
                <td className="px-4 py-3 font-medium text-foreground">
                  {scenario.title}
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {scenario.category}
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {scenario.persona}
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {scenario.goal_type}
                </td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => openEdit(scenario)}
                      aria-label={`Edit ${scenario.title}`}
                      className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface hover:text-foreground"
                    >
                      <Pencil className="h-4 w-4" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(scenario)}
                      aria-label={`Delete ${scenario.title}`}
                      className="rounded-lg p-1.5 text-muted-foreground hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {scenarios && scenarios.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-muted-foreground"
                >
                  No custom scenarios yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <Modal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          resetPreview();
        }}
        title={editingId ? "Edit Scenario" : "New Scenario"}
        className="max-w-lg"
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">
              Category
            </label>
            <select
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              className="h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            >
              {EXPLORE_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <Input
            label="Persona"
            placeholder="e.g. Product Manager"
            value={form.persona}
            onChange={(e) => setForm({ ...form, persona: e.target.value })}
          />
          <Textarea
            label="Intent (shown to the learner)"
            rows={2}
            value={form.intent}
            onChange={(e) => setForm({ ...form, intent: e.target.value })}
            hint="Short blurb on the pre-scenario screen, e.g. 'Practice asking for a raise professionally.'"
          />
          <Textarea
            label="Persona instructions / scenario goal (prompt)"
            rows={5}
            value={form.system_prompt}
            onChange={(e) =>
              setForm({ ...form, system_prompt: e.target.value })
            }
            hint="The actual instructions given to the AI: who it plays, how it should react, what the learner must accomplish."
          />
          <Input
            label="Opening line (optional)"
            value={form.opening_line}
            onChange={(e) => setForm({ ...form, opening_line: e.target.value })}
          />
          <Input
            label="Target vocabulary"
            placeholder="e.g. compensation, value, market rate"
            value={vocabText}
            onChange={(e) => setVocabText(e.target.value)}
            hint="Comma-separated, at least 3 words."
          />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">
              Goal type
            </label>
            <select
              value={form.goal_type}
              onChange={(e) =>
                setForm({
                  ...form,
                  goal_type: e.target.value as CustomScenarioInput["goal_type"],
                })
              }
              className="h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            >
              <option value="roleplay">Roleplay</option>
              <option value="negotiation">Negotiation</option>
            </select>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">
              Professional tone expected
            </span>
            <Switch
              checked={form.corporate_tone}
              onCheckedChange={(checked) =>
                setForm({ ...form, corporate_tone: checked })
              }
              label="Professional tone expected"
              hideLabel
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">
              Medical-emergency safety break
            </span>
            <Switch
              checked={form.safety_mode}
              onCheckedChange={(checked) =>
                setForm({ ...form, safety_mode: checked })
              }
              label="Medical-emergency safety break"
              hideLabel
            />
          </div>

          <Button
            variant="outline"
            size="sm"
            loading={previewOpen && previewLoading && previewTurns.length === 0}
            onClick={handleTogglePreview}
          >
            <FlaskConical className="h-4 w-4" aria-hidden="true" />
            {previewOpen ? "Hide sandbox tester" : "Test this scenario"}
          </Button>

          {previewOpen ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-3">
              <p className="text-xs text-muted-foreground">
                Try the prompt above against the AI — nothing here is saved or
                shown to learners.
              </p>
              <div className="flex max-h-48 flex-col gap-2 overflow-y-auto">
                {previewTurns.map((turn, i) => (
                  <div
                    key={i}
                    className={
                      turn.role === "user"
                        ? "ml-auto max-w-[85%]"
                        : "max-w-[85%]"
                    }
                  >
                    <div
                      className={
                        turn.role === "user"
                          ? "rounded-lg bg-primary px-3 py-2 text-xs text-primary-foreground"
                          : "rounded-lg bg-secondary px-3 py-2 text-xs text-secondary-foreground"
                      }
                    >
                      {turn.content}
                    </div>
                  </div>
                ))}
              </div>
              {previewError ? (
                <p className="text-xs text-danger">{previewError}</p>
              ) : null}
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={previewInput}
                  onChange={(e) => setPreviewInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendPreview();
                    }
                  }}
                  placeholder="Try a test message..."
                  className="h-9 flex-1 rounded-lg border border-input bg-surface-elevated px-3 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
                />
                <Button
                  size="sm"
                  loading={previewLoading && previewTurns.length > 0}
                  disabled={!previewInput.trim()}
                  onClick={handleSendPreview}
                >
                  Send
                </Button>
              </div>
            </div>
          ) : null}

          {formError ? (
            <p className="text-sm text-danger">{formError}</p>
          ) : null}

          <Button size="lg" loading={saving} onClick={handleSave}>
            {editingId ? "Save Changes" : "Publish Scenario"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
