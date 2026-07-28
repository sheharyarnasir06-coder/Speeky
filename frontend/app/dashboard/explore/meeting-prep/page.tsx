import Link from "next/link";
import { ArrowLeft, CheckCircle2, Sparkles } from "lucide-react";
import { AiCoachAvatar } from "@/components/common/AiCoachAvatar";
import { UserChatAvatar } from "@/components/common/UserChatAvatar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * US-66 mockup — the GitHub issue ("Workplace English - Meeting Preparation
 * Feedback UI") shipped with no description, acceptance criteria, or backend
 * endpoint. There is no session/transcript API yet (Backend has no
 * conversation-practice routes at all), so this whole screen is static
 * placeholder content.
 *
 * TODO(backend): needs something like
 *   GET /api/sessions/{sessionId}/feedback ->
 *     { transcript: {speaker, text, tags}[], skill_scores: {...}, next_steps: string[] }
 * — same shape family as assessment_service.get_results_summary — before
 * this can show a real session's feedback instead of fixture data.
 */

const TRANSCRIPT = [
  {
    speaker: "coach" as const,
    text: "Let's prepare for tomorrow's stakeholder meeting. How would you open by summarizing last quarter's progress?",
  },
  {
    speaker: "user" as const,
    text: "Sure — last quarter we hit our delivery targets, but I want to flag that scope grew mid-sprint.",
    tags: [{ label: "Clear structure", tone: "positive" as const }],
  },
  {
    speaker: "coach" as const,
    text: "Good framing. Try leading with the outcome before the caveat — it reads more confidently to stakeholders.",
  },
  {
    speaker: "user" as const,
    text: "We delivered on time despite mid-sprint scope growth, and here's how we managed it.",
    tags: [{ label: "Confident framing", tone: "positive" as const }],
  },
];

const SKILL_SCORES = [
  { label: "Clarity", value: 88 },
  { label: "Professional Tone", value: 79 },
  { label: "Structure", value: 91 },
];

export default function MeetingPrepFeedbackPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <Link
        href="/dashboard/explore"
        className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Back to Explore
      </Link>

      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Meeting Preparation — Session Feedback
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Sample feedback for a workplace meeting-preparation session. This
          screen is a design placeholder — practice sessions aren&apos;t wired
          to a live AI conversation yet.
        </p>
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Transcript &amp; Feedback
        </h2>
        <div className="mt-5 flex flex-col gap-5">
          {TRANSCRIPT.map((line, i) => (
            <div
              key={i}
              className={
                line.speaker === "user"
                  ? "ml-auto flex max-w-md items-start gap-2"
                  : "flex max-w-xl items-start gap-2"
              }
            >
              {line.speaker === "coach" ? <AiCoachAvatar className="mt-5" /> : null}
              <div className="min-w-0 flex-1">
                <span
                  className={cn(
                    "mb-1 block text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                    line.speaker === "user" && "text-right",
                  )}
                >
                  {line.speaker === "user" ? "You" : "Coach"}
                </span>
                <div
                  className={
                    line.speaker === "user"
                      ? "rounded-xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground"
                      : "rounded-xl rounded-tl-sm bg-secondary px-4 py-3 text-sm text-secondary-foreground"
                  }
                >
                  {line.text}
                </div>
                {line.tags ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {line.tags.map((tag) => (
                      <span
                        key={tag.label}
                        className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2.5 py-1 text-xs font-medium text-success"
                      >
                        <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                        {tag.label}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              {line.speaker === "user" ? <UserChatAvatar className="mt-5" /> : null}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Skill Scores
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {SKILL_SCORES.map((skill) => (
            <div key={skill.label} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
                <span>{skill.label}</span>
                <span className="text-foreground">{skill.value}%</span>
              </div>
              <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
                <div
                  className="h-1.5 rounded-full bg-primary"
                  style={{ width: `${skill.value}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary">
          <Sparkles className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">Coach&apos;s tip</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Leading with outcomes before caveats reads as more confident to
            stakeholders — keep practicing that structure in your next session.
          </p>
        </div>
      </div>

      <Button href="/dashboard/explore" size="lg" variant="outline" className="self-center">
        Back to Scenarios
      </Button>
    </div>
  );
}
