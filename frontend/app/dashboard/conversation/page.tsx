"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "react-toastify";
import { Lock, MessagesSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { listTopics, startConversation, type ConversationTopic } from "@/lib/conversation";
import { useAssessmentAccess } from "@/contexts/AssessmentContext";

export default function ConversationPage() {
  const router = useRouter();
  const { access } = useAssessmentAccess();
  const isUnlocked = access?.access_level === "full_access";

  const [topics, setTopics] = React.useState<ConversationTopic[]>([]);
  const [selectedTopic, setSelectedTopic] = React.useState<string | null>(null);
  const [customTopic, setCustomTopic] = React.useState("");
  const [useCustom, setUseCustom] = React.useState(false);
  const [showCorrections, setShowCorrections] = React.useState(false);
  const [isStarting, setIsStarting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!isUnlocked) return;
    listTopics()
      .then((data) => setTopics(data.topics))
      .catch(() => toast.error("Couldn't load conversation topics."));
  }, [isUnlocked]);

  async function handleStart() {
    if (!useCustom && !selectedTopic) return;
    if (useCustom && customTopic.trim().length < 3) {
      setError("Enter at least 3 characters for your topic.");
      return;
    }
    setError(null);
    setIsStarting(true);
    try {
      const session = await startConversation(
        useCustom
          ? { custom_topic: customTopic.trim(), show_corrections: showCorrections }
          : { topic_key: selectedTopic!, show_corrections: showCorrections }
      );
      router.push(`/dashboard/conversation/${session.session_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setIsStarting(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          AI Conversation Practice
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Have an open-ended conversation with your AI coach on any topic.
        </p>
      </div>

      {!isUnlocked ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          {access?.locked_message ??
            "Complete your baseline assessment to unlock AI Conversation Practice."}
        </div>
      ) : (
        <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <p className="text-sm font-medium text-foreground">Choose a topic</p>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {topics.map((topic) => (
              <button
                key={topic.key}
                type="button"
                onClick={() => {
                  setUseCustom(false);
                  setSelectedTopic(topic.key);
                }}
                className={cn(
                  "rounded-xl border p-3 text-left text-sm font-medium transition-colors",
                  !useCustom && selectedTopic === topic.key
                    ? "border-primary bg-secondary text-foreground"
                    : "border-border text-muted-foreground hover:bg-surface",
                )}
              >
                {topic.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setUseCustom(true)}
              className={cn(
                "rounded-xl border p-3 text-left text-sm font-medium transition-colors",
                useCustom
                  ? "border-primary bg-secondary text-foreground"
                  : "border-border text-muted-foreground hover:bg-surface",
              )}
            >
              Custom topic
            </button>
          </div>

          {useCustom ? (
            <input
              type="text"
              value={customTopic}
              onChange={(event) => setCustomTopic(event.target.value)}
              placeholder="What do you want to talk about?"
              className="mt-4 h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
            />
          ) : null}

          <div className="mt-4">
            <Checkbox
              checked={showCorrections}
              onChange={(event) => setShowCorrections(event.target.checked)}
              label="Show inline grammar corrections while I type"
            />
          </div>

          {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

          <Button
            size="lg"
            className="mt-5"
            loading={isStarting}
            disabled={useCustom ? customTopic.trim().length < 3 : !selectedTopic}
            onClick={handleStart}
          >
            <MessagesSquare className="h-4 w-4" aria-hidden="true" />
            Start Conversation
          </Button>
        </div>
      )}
    </div>
  );
}
