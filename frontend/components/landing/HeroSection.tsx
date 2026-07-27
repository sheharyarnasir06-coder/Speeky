"use client";

import * as React from "react";
import { ArrowRight, PlayCircle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { VoiceWave } from "@/components/common/VoiceWave";
import { TRUST_INDICATORS } from "@/lib/mock-data";

const PRACTICE_MOMENTS = [
  {
    prompt: "Tell me about a time you handled a disagreement with a teammate.",
    answer:
      "Sure — on my last project, a teammate and I disagreed on the timeline, so I suggested we walk through the risks together...",
    feedback: "Confidence +4 · Clear structure, strong example",
  },
  {
    prompt: "Practice opening tomorrow's client update.",
    answer:
      "Good morning everyone — I'll start with where we are, then the two decisions we need before Friday.",
    feedback: "Pacing steady · Opening feels calm and prepared",
  },
  {
    prompt: "Rehearse a difficult conversation with your manager.",
    answer:
      "I wanted to talk through priorities, because I can deliver better work if we agree on what matters most this week.",
    feedback: "Tone balanced · Direct without sounding defensive",
  },
];

export function HeroSection() {
  const [activeMoment, setActiveMoment] = React.useState(0);
  const currentMoment = PRACTICE_MOMENTS[activeMoment];

  React.useEffect(() => {
    const interval = window.setInterval(() => {
      setActiveMoment((index) => (index + 1) % PRACTICE_MOMENTS.length);
    }, 4200);

    return () => window.clearInterval(interval);
  }, []);

  return (
    <section className="relative isolate overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-20 bg-[radial-gradient(70%_55%_at_50%_0%,hsl(var(--secondary))_0%,hsl(var(--background))_72%)] dark:bg-[radial-gradient(70%_55%_at_50%_0%,hsl(var(--accent)/0.16)_0%,hsl(var(--background))_72%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-[-10rem] top-24 -z-10 h-72 w-72 rounded-full bg-primary/10 blur-3xl dark:bg-accent/10"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-[-12rem] top-48 -z-10 h-96 w-96 rounded-full bg-accent/10 blur-3xl dark:bg-primary/10"
      />
      <VoiceWave className="top-24 -z-10 opacity-50 dark:opacity-70" />

      <div className="container flex flex-col items-center gap-10 py-24 text-center sm:py-32">
        <div className="inline-flex animate-fade-in items-center gap-2 rounded-xl border border-border bg-surface/80 px-4 py-1.5 text-sm font-medium text-muted-foreground shadow-sm backdrop-blur">
          <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" />
          Private AI practice for the conversations that matter
        </div>

        <h1 className="max-w-4xl animate-fade-up text-balance font-serif text-5xl font-semibold tracking-tight text-foreground sm:text-6xl md:text-7xl">
          Rehearse the moment before it becomes real.
        </h1>

        <p className="max-w-2xl animate-fade-up text-balance text-lg leading-8 text-muted-foreground sm:text-xl">
          Speeky helps you practice interviews, meetings, presentations, and difficult conversations out loud, with feedback that feels useful instead of judgmental.
        </p>

        <div className="flex animate-fade-up flex-col items-center gap-4 sm:flex-row">
          <Button size="lg" className="gap-2" href="/signup">
            Start Practicing
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button size="lg" variant="outline" className="gap-2" href="#how-it-works">
            <PlayCircle className="h-4 w-4" aria-hidden="true" />
            See How It Works
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-sm text-muted-foreground">
          {TRUST_INDICATORS.map((item) => (
            <span key={item.id} className="inline-flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
              {item.label}
            </span>
          ))}
        </div>

        <div className="relative mt-8 w-full max-w-5xl animate-fade-up">
          <div className="relative overflow-hidden rounded-[1.35rem] border border-border/80 bg-surface-elevated shadow-sm dark:bg-surface-elevated">
            <VoiceWave compact className="bottom-3 opacity-25 dark:opacity-38" />
            <div className="relative flex items-center gap-2 border-b border-border/70 bg-surface/40 px-5 py-3 backdrop-blur">
              <span className="h-2.5 w-2.5 rounded-full bg-danger/60" aria-hidden="true" />
              <span className="h-2.5 w-2.5 rounded-full bg-warning/60" aria-hidden="true" />
              <span className="h-2.5 w-2.5 rounded-full bg-success/60" aria-hidden="true" />
              <span className="ml-3 text-xs text-muted-foreground">
                Speeky — private practice session
              </span>
            </div>
            <div className="relative flex min-h-[17rem] flex-col justify-center gap-5 p-6 text-left sm:p-10">
              <div className="max-w-xl rounded-2xl rounded-tl-sm border border-border/70 bg-surface/75 px-5 py-3 text-sm text-foreground shadow-sm backdrop-blur">
                {currentMoment.prompt}
              </div>
              <div className="ml-auto max-w-xl rounded-2xl rounded-tr-sm border border-accent/25 bg-accent/15 px-5 py-4 text-sm leading-6 text-foreground shadow-[0_18px_55px_-36px_hsl(var(--accent))] backdrop-blur dark:bg-accent/18">
                {currentMoment.answer}
              </div>
              <div className="flex items-center gap-2 self-start rounded-xl border border-accent/20 bg-surface/70 px-4 py-2 text-xs text-muted-foreground shadow-sm backdrop-blur">
                <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                {currentMoment.feedback}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
