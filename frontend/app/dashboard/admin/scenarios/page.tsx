"use client";

import * as React from "react";
import { toast } from "react-toastify";
import {
  Archive,
  FlaskConical,
  Gauge,
  History,
  Pencil,
  Plus,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/lib/api";
import {
  adminArchiveCustomScenario,
  adminAssessReadiness,
  adminCreateCustomScenario,
  adminEvaluateTemplate,
  adminListCustomScenarios,
  adminListScenarioVersions,
  adminRestoreCustomScenario,
  adminRollbackCustomScenario,
  adminUpdateCustomScenario,
  previewCustomScenario,
  type CustomScenario,
  type CustomScenarioInput,
  type PublishGateError,
  type ScenarioPreviewTurn,
  type ScenarioVersionEntry,
} from "@/lib/scenario";
import { adminListCategories, type Category } from "@/lib/categories";
import { useAuth } from "@/contexts/AuthContext";

const MAX_VOCAB = 15;
const MAX_PROMPT_CHARS = 4000;

const DIFFICULTY_OPTIONS = [
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
];

const GOAL_TYPE_OPTIONS = [
  { value: "roleplay", label: "Roleplay" },
  { value: "negotiation", label: "Negotiation" },
];

const EMPTY_FORM: CustomScenarioInput = {
  title: "",
  category: "",
  persona: "",
  intent: "",
  system_prompt: "",
  opening_line: "",
  target_vocab: [],
  goal_type: "roleplay",
  difficulty: "intermediate",
  safety_mode: false,
  corporate_tone: true,
  tested: false,
  quality_acknowledged: false,
};

// Mirrors backend ARCHIVE_PURGE_GRACE_HOURS (scenario_service.py) — archived scenarios
// with nobody mid-session are auto-deleted this long after archiving, swept whenever
// this page loads. Purely informational here; the backend is the source of truth.
const ARCHIVE_PURGE_GRACE_HOURS = 24;

function archivePurgeHint(archivedAt: string): string {
  const elapsedHours = (Date.now() - new Date(archivedAt).getTime()) / 3_600_000;
  const remaining = Math.ceil(ARCHIVE_PURGE_GRACE_HOURS - elapsedHours);
  return remaining > 0
    ? `Auto-deletes in ~${remaining}h if unused, unless restored`
    : "Eligible for auto-delete once no one is mid-session";
}

function scoreTone(score: number | null): "success" | "warning" | "danger" | "neutral" {
  if (score === null) return "neutral";
  if (score >= 70) return "success";
  if (score >= 50) return "warning";
  return "danger";
}

export default function AdminScenariosPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [scenarios, setScenarios] = React.useState<CustomScenario[] | null>(null);
  const [categories, setCategories] = React.useState<Category[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [modalOpen, setModalOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editingScenario, setEditingScenario] = React.useState<CustomScenario | null>(null);
  const [form, setForm] = React.useState<CustomScenarioInput>(EMPTY_FORM);
  const [vocabText, setVocabText] = React.useState("");
  const [formError, setFormError] = React.useState<string | null>(null);
  const [gateInfo, setGateInfo] = React.useState<PublishGateError | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [evaluating, setEvaluating] = React.useState(false);
  const [assessingReadiness, setAssessingReadiness] = React.useState(false);

  const [previewOpen, setPreviewOpen] = React.useState(false);
  const [previewTurns, setPreviewTurns] = React.useState<ScenarioPreviewTurn[]>([]);
  const [previewInput, setPreviewInput] = React.useState("");
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [previewError, setPreviewError] = React.useState<string | null>(null);

  const [versionsFor, setVersionsFor] = React.useState<CustomScenario | null>(null);
  const [versions, setVersions] = React.useState<ScenarioVersionEntry[] | null>(null);
  const [rollingBack, setRollingBack] = React.useState<number | null>(null);

  const isAdmin = user?.role === "ADMIN" || user?.role === "SUPER_ADMIN";

  const refresh = React.useCallback(() => {
    adminListCustomScenarios()
      .then((data) => setScenarios(data.scenarios))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load scenarios."));
    adminListCategories()
      .then((data) => setCategories(data.categories))
      .catch(() => {
        // Non-fatal — the category select just falls back to an empty list.
      });
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
    setEditingScenario(null);
    setForm({ ...EMPTY_FORM, category: categories[0]?.name ?? "" });
    setVocabText("");
    setFormError(null);
    setGateInfo(null);
    resetPreview();
    setModalOpen(true);
  }

  function openEdit(scenario: CustomScenario) {
    setEditingId(scenario.id);
    setEditingScenario(scenario);
    setForm({
      title: scenario.title,
      category: scenario.category,
      persona: scenario.persona,
      intent: scenario.intent,
      system_prompt: scenario.system_prompt,
      opening_line: scenario.opening_line ?? "",
      target_vocab: scenario.target_vocab,
      goal_type: scenario.goal_type,
      difficulty: scenario.difficulty,
      safety_mode: scenario.safety_mode,
      corporate_tone: scenario.corporate_tone,
      tested: scenario.sandbox_tested,
      quality_acknowledged: false,
    });
    setVocabText(scenario.target_vocab.join(", "));
    setFormError(null);
    setGateInfo(null);
    resetPreview();
    setModalOpen(true);
  }

  // Any further content edit invalidates a pending acknowledgment/gate result — the
  // admin needs to see fresh feedback (or re-test) for whatever they just changed.
  function updateForm(patch: Partial<CustomScenarioInput>) {
    setForm((prev) => ({ ...prev, ...patch }));
    setGateInfo(null);
  }

  function currentVocab() {
    return vocabText.split(",").map((w) => w.trim()).filter(Boolean).slice(0, MAX_VOCAB);
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
      const { reply } = await previewCustomScenario({
        persona: form.persona || "Persona",
        system_prompt: form.system_prompt || "Stay in character.",
        opening_line: form.opening_line,
        target_vocab: currentVocab(),
        goal_type: form.goal_type,
        safety_mode: form.safety_mode,
        corporate_tone: form.corporate_tone,
        turns: [],
      });
      setPreviewTurns([{ role: "assistant", content: reply }]);
      setForm((prev) => ({ ...prev, tested: true }));
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : "Couldn't start the preview.");
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
      const { reply } = await previewCustomScenario({
        persona: form.persona || "Persona",
        system_prompt: form.system_prompt || "Stay in character.",
        opening_line: form.opening_line,
        target_vocab: currentVocab(),
        goal_type: form.goal_type,
        safety_mode: form.safety_mode,
        corporate_tone: form.corporate_tone,
        turns: turnsSoFar,
        message,
      });
      setPreviewTurns((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleSave(acknowledge = false) {
    setFormError(null);
    if (!acknowledge) setGateInfo(null);
    const targetVocab = currentVocab();
    if (targetVocab.length < 3) {
      setFormError("Add at least 3 target vocabulary words, separated by commas.");
      return;
    }
    if (form.intent.trim().length < 10) {
      setFormError("Add a short learner-facing description (at least 10 characters).");
      return;
    }
    if (!form.category) {
      setFormError("Choose a category — add one under Content Management → Categories first.");
      return;
    }
    const payload: CustomScenarioInput = {
      ...form,
      target_vocab: targetVocab,
      quality_acknowledged: acknowledge,
    };
    setSaving(true);
    try {
      const saved = editingId
        ? await adminUpdateCustomScenario(editingId, payload)
        : await adminCreateCustomScenario(payload);
      setModalOpen(false);
      refresh();
      toast.success(editingId ? "Scenario updated." : "Scenario created.");
      if (targetVocab.length !== saved.target_vocab.length) {
        toast.info("Duplicate words removed from the vocabulary list.");
      }
      if (!editingId) {
        // Keep editing the freshly-created scenario so Evaluate/Readiness are reachable.
        openEdit(saved);
      }
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === "object" && "gate" in err.body) {
        const gate = err.body as PublishGateError;
        setGateInfo(gate);
        setFormError(gate.error);
      } else {
        setFormError(err instanceof ApiError ? err.message : "Couldn't save this scenario.");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleEvaluate() {
    if (!editingId) return;
    setEvaluating(true);
    try {
      const updated = await adminEvaluateTemplate(editingId);
      setEditingScenario(updated);
      toast.success("Quality + confidence evaluated.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Evaluation failed.");
    } finally {
      setEvaluating(false);
    }
  }

  async function handleReadiness() {
    if (!editingId) return;
    setAssessingReadiness(true);
    try {
      const updated = await adminAssessReadiness(editingId);
      setEditingScenario(updated);
      toast.success("Readiness assessed.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Readiness check failed.");
    } finally {
      setAssessingReadiness(false);
    }
  }

  async function handleArchive(scenario: CustomScenario) {
    if (!window.confirm(`Archive "${scenario.title}"? Learners won't be able to start new sessions, but anyone mid-session can finish.`))
      return;
    try {
      await adminArchiveCustomScenario(scenario.id);
      refresh();
      toast.success("Scenario archived.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't archive this scenario.");
    }
  }

  async function handleRestore(scenario: CustomScenario) {
    try {
      await adminRestoreCustomScenario(scenario.id);
      refresh();
      toast.success("Scenario restored.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't restore this scenario.");
    }
  }

  async function openVersions(scenario: CustomScenario) {
    setVersionsFor(scenario);
    setVersions(null);
    try {
      const data = await adminListScenarioVersions(scenario.id);
      setVersions(data.versions);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't load version history.");
      setVersionsFor(null);
    }
  }

  async function handleRollback(version: number) {
    if (!versionsFor) return;
    if (
      !window.confirm(
        `Roll back to version ${version}? This permanently deletes every version newer than ${version} — that history cannot be recovered afterward. The scenario will need to be re-tested and re-evaluated before it can be saved again.`,
      )
    )
      return;
    setRollingBack(version);
    try {
      await adminRollbackCustomScenario(versionsFor.id, version);
      setVersionsFor(null);
      refresh();
      toast.success(`Rolled back to version ${version}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Rollback failed.");
    } finally {
      setRollingBack(null);
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

  const categoryOptions = categories.map((c) => ({ value: c.name, label: c.name }));

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-serif text-h1 font-semibold text-foreground">
            Custom Scenarios
          </h1>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Add or edit Scenario-Based Learning practice scenarios. Changes go live for
            learners immediately — no app update needed.
          </p>
        </div>
        <Button size="md" onClick={openCreate} disabled={categories.length === 0}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          New Scenario
        </Button>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {categories.length === 0 ? (
        <p className="text-sm text-warning">
          No categories exist yet — add one under Categories before creating a scenario.
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface-elevated">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Difficulty</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Scores</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(scenarios ?? []).map((scenario) => (
              <tr key={scenario.id} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-medium text-foreground">
                  {scenario.title}
                  <span className="ml-1.5 text-xs text-muted-foreground">v{scenario.version}</span>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{scenario.category}</td>
                <td className="px-4 py-3 text-muted-foreground capitalize">{scenario.difficulty}</td>
                <td className="px-4 py-3">
                  <Badge tone={scenario.status === "ACTIVE" ? "success" : "neutral"}>
                    {scenario.status === "ACTIVE" ? "Active" : "Archived"}
                  </Badge>
                  {scenario.status === "ARCHIVED" && scenario.archived_at ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {archivePurgeHint(scenario.archived_at)}
                    </p>
                  ) : null}
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-1.5">
                    <Badge tone={scoreTone(scenario.quality_score)} title="Quality">
                      Q {scenario.quality_score ?? "—"}
                    </Badge>
                    <Badge tone={scoreTone(scenario.confidence_score)} title="Confidence">
                      C {scenario.confidence_score ?? "—"}
                    </Badge>
                    <Badge tone={scoreTone(scenario.readiness_score)} title="Readiness">
                      R {scenario.readiness_score ?? "—"}
                    </Badge>
                  </div>
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
                      onClick={() => openVersions(scenario)}
                      aria-label={`Version history for ${scenario.title}`}
                      className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface hover:text-foreground"
                    >
                      <History className="h-4 w-4" aria-hidden="true" />
                    </button>
                    {scenario.status === "ACTIVE" ? (
                      <button
                        type="button"
                        onClick={() => handleArchive(scenario)}
                        aria-label={`Archive ${scenario.title}`}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-danger/10 hover:text-danger"
                      >
                        <Archive className="h-4 w-4" aria-hidden="true" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleRestore(scenario)}
                        aria-label={`Restore ${scenario.title}`}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-success/10 hover:text-success"
                      >
                        <RotateCcw className="h-4 w-4" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {scenarios && scenarios.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
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
            onChange={(e) => updateForm({ title: e.target.value })}
          />
          <Select
            label="Category"
            value={form.category}
            onChange={(e) => updateForm({ category: e.target.value })}
            options={categoryOptions}
          />
          <Select
            label="Difficulty"
            value={form.difficulty}
            onChange={(e) =>
              updateForm({ difficulty: e.target.value as CustomScenarioInput["difficulty"] })
            }
            options={DIFFICULTY_OPTIONS}
          />
          <Input
            label="Persona"
            placeholder="e.g. Product Manager"
            value={form.persona}
            onChange={(e) => updateForm({ persona: e.target.value })}
          />
          <Textarea
            label="Intent (shown to the learner)"
            rows={2}
            value={form.intent}
            onChange={(e) => updateForm({ intent: e.target.value })}
            hint="Short blurb on the pre-scenario screen, e.g. 'Practice asking for a raise professionally.'"
          />
          <Textarea
            label="Persona instructions / scenario goal (prompt)"
            rows={5}
            value={form.system_prompt}
            maxLength={MAX_PROMPT_CHARS}
            onChange={(e) => updateForm({ system_prompt: e.target.value, tested: false })}
            hint={`The actual instructions given to the AI: who it plays, how it should react, what the learner must accomplish. ${form.system_prompt.length}/${MAX_PROMPT_CHARS} characters. Never ask learners for real passwords, card numbers, or other sensitive data.`}
          />
          <Input
            label="Opening line (optional)"
            value={form.opening_line}
            onChange={(e) => updateForm({ opening_line: e.target.value })}
          />
          <Input
            label="Target vocabulary"
            placeholder="e.g. compensation, value, market rate"
            value={vocabText}
            onChange={(e) => {
              setVocabText(e.target.value);
              setGateInfo(null);
            }}
            hint={`Comma-separated, 3-${MAX_VOCAB} words, no duplicates. ${currentVocab().length}/${MAX_VOCAB}.`}
          />
          <Select
            label="Goal type"
            value={form.goal_type}
            onChange={(e) =>
              updateForm({ goal_type: e.target.value as CustomScenarioInput["goal_type"] })
            }
            options={GOAL_TYPE_OPTIONS}
          />
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">Professional tone expected</span>
            <Switch
              checked={form.corporate_tone}
              onCheckedChange={(checked) => updateForm({ corporate_tone: checked })}
              label="Professional tone expected"
              hideLabel
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">Medical-emergency safety break</span>
            <Switch
              checked={form.safety_mode}
              onCheckedChange={(checked) => updateForm({ safety_mode: checked })}
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
          {form.tested ? (
            <Badge tone="success" className="w-fit">Tested this session</Badge>
          ) : (
            <Badge tone="warning" className="w-fit">Not tested since last change</Badge>
          )}

          {previewOpen ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-3">
              <p className="text-xs text-muted-foreground">
                Try the prompt above against the AI — nothing here is saved or shown to learners.
              </p>
              <div className="flex max-h-48 flex-col gap-2 overflow-y-auto">
                {previewTurns.map((turn, i) => (
                  <div key={i} className={turn.role === "user" ? "ml-auto max-w-[85%]" : "max-w-[85%]"}>
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
              {previewError ? <p className="text-xs text-danger">{previewError}</p> : null}
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
                <Button size="sm" loading={previewLoading && previewTurns.length > 0} disabled={!previewInput.trim()} onClick={handleSendPreview}>
                  Send
                </Button>
              </div>
            </div>
          ) : null}

          {formError ? <p className="text-sm text-danger">{formError}</p> : null}

          {gateInfo ? (
            <div className="flex flex-col gap-2 rounded-xl border border-warning/30 bg-warning/5 p-3 text-xs">
              {gateInfo.gate === "needs_acknowledgment" ? (
                <>
                  <div className="flex items-center gap-2">
                    <Badge tone={scoreTone(gateInfo.quality_score ?? null)}>
                      Quality {gateInfo.quality_score}/100
                    </Badge>
                    <Badge tone={scoreTone(gateInfo.confidence_score ?? null)}>
                      Confidence {gateInfo.confidence_score}/100
                    </Badge>
                  </div>
                  {gateInfo.quality_recommendations?.length ? (
                    <ul className="list-inside list-disc text-muted-foreground">
                      {gateInfo.quality_recommendations.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  ) : null}
                  {gateInfo.confidence_warnings?.length ? (
                    <ul className="list-inside list-disc text-warning">
                      {gateInfo.confidence_warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  ) : null}
                  {gateInfo.readiness_missing?.length ? (
                    <p className="text-muted-foreground">Missing: {gateInfo.readiness_missing.join(", ")}</p>
                  ) : null}
                  <Button size="sm" variant="outline" loading={saving} onClick={() => handleSave(true)}>
                    Publish Anyway
                  </Button>
                </>
              ) : (
                <p className="text-muted-foreground">Run the sandbox tester above, then try saving again.</p>
              )}
            </div>
          ) : null}

          <Button size="lg" loading={saving} onClick={() => handleSave()}>
            {editingId ? "Save Changes" : "Publish Scenario"}
          </Button>

          {editingId ? (
            <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" loading={evaluating} onClick={handleEvaluate}>
                  <Gauge className="h-4 w-4" aria-hidden="true" />
                  Evaluate Quality + Confidence
                </Button>
                <Button size="sm" variant="outline" loading={assessingReadiness} onClick={handleReadiness}>
                  Assess Readiness
                </Button>
              </div>

              {editingScenario?.quality_score !== null && editingScenario?.quality_score !== undefined ? (
                <div className="flex flex-col gap-1 text-xs">
                  <div className="flex items-center gap-2">
                    <Badge tone={scoreTone(editingScenario.quality_score)}>
                      Quality {editingScenario.quality_score}/100
                    </Badge>
                    <Badge tone={scoreTone(editingScenario.confidence_score)}>
                      Confidence {editingScenario.confidence_score}/100
                    </Badge>
                  </div>
                  {editingScenario.quality_feedback?.recommendations?.length ? (
                    <ul className="list-inside list-disc text-muted-foreground">
                      {editingScenario.quality_feedback.recommendations.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  ) : null}
                  {editingScenario.confidence_feedback?.warnings?.length ? (
                    <ul className="list-inside list-disc text-warning">
                      {editingScenario.confidence_feedback.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  ) : null}
                  {editingScenario.confidence_feedback?.guardrail_suggestions?.length ? (
                    <>
                      <p className="font-medium text-foreground">Suggested guardrails:</p>
                      <ul className="list-inside list-disc text-muted-foreground">
                        {editingScenario.confidence_feedback.guardrail_suggestions.map((g, i) => (
                          <li key={i}>{g}</li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </div>
              ) : null}

              {editingScenario?.readiness_checklist ? (
                <div className="flex flex-col gap-1 text-xs">
                  <Badge tone={editingScenario.readiness_checklist.ready ? "success" : "warning"} className="w-fit">
                    {editingScenario.readiness_checklist.ready
                      ? "Ready to publish"
                      : "Not recommended for publication yet"}
                  </Badge>
                  {editingScenario.readiness_checklist.missing.length ? (
                    <p className="text-muted-foreground">
                      Missing: {editingScenario.readiness_checklist.missing.join(", ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </Modal>

      <Modal
        open={Boolean(versionsFor)}
        onClose={() => setVersionsFor(null)}
        title={versionsFor ? `Version History — ${versionsFor.title}` : "Version History"}
        className="max-w-lg"
      >
        <div className="flex flex-col gap-3">
          {versions === null ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : versions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No prior versions yet — this is the first.</p>
          ) : (
            versions.map((v) => (
              <div
                key={v.version}
                className="flex items-center justify-between rounded-xl border border-border bg-surface p-3"
              >
                <div>
                  <p className="text-sm font-medium text-foreground">
                    Version {v.version}
                    {versionsFor?.version === v.version ? (
                      <span className="ml-1.5 text-xs text-muted-foreground">(current)</span>
                    ) : null}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(v.created_at).toLocaleString()} — {String(v.snapshot.persona ?? "")}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  loading={rollingBack === v.version}
                  onClick={() => handleRollback(v.version)}
                >
                  Rollback
                </Button>
              </div>
            ))
          )}
        </div>
      </Modal>
    </div>
  );
}
