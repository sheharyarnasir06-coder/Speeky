"use client";

import Image from "next/image";
import { ArrowRight, BarChart3, MessageCircle, PlayCircle, ShieldCheck, Sparkles, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TRUST_INDICATORS } from "@/lib/mock-data";

const HERO_FEATURES = [
  { label: "Built for interviews & meetings", icon: BarChart3, tone: "text-primary bg-primary/10" },
  { label: "Judgment-free private practice", icon: ShieldCheck, tone: "text-danger bg-danger/10" },
  { label: "AI feedback that actually helps", icon: MessageCircle, tone: "text-accent bg-accent/10" },
  { label: "Practice sessions available 24/7", icon: Star, tone: "text-warning bg-warning/10" },
];

export function HeroSection() {
  return (
    <section className="relative isolate overflow-hidden border-b border-border bg-background">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-20 bg-[radial-gradient(55%_45%_at_88%_25%,hsl(var(--primary)/0.12),transparent_70%),radial-gradient(45%_35%_at_12%_18%,hsl(var(--accent)/0.10),transparent_72%),linear-gradient(180deg,hsl(var(--surface))_0%,hsl(var(--background))_100%)] dark:bg-[radial-gradient(55%_45%_at_88%_25%,hsl(var(--primary)/0.14),transparent_70%),radial-gradient(45%_35%_at_12%_18%,hsl(var(--accent)/0.13),transparent_72%),linear-gradient(180deg,hsl(var(--background))_0%,hsl(var(--surface))_100%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-16 top-24 -z-10 h-52 w-52 rounded-full bg-accent/10 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 bottom-16 -z-10 h-72 w-72 rounded-full bg-primary/12 blur-3xl"
      />

      <div className="container grid min-h-[calc(100vh-4rem)] items-center gap-12 py-20 lg:grid-cols-[1.02fr_0.98fr] lg:py-24">
        <div className="flex max-w-3xl flex-col items-start">
          <div className="inline-flex animate-fade-in items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-4 py-2 text-sm font-medium text-primary shadow-sm">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            Private AI practice for the conversations that matter
          </div>

          <h1 className="mt-8 max-w-4xl animate-fade-up text-balance font-serif text-5xl font-semibold tracking-tight text-foreground sm:text-6xl md:text-7xl">
            Rehearse the moment before it becomes{" "}
            <span className="text-accent">real.</span>
          </h1>

          <p className="mt-7 max-w-2xl animate-fade-up text-lg leading-8 text-muted-foreground sm:text-xl">
            Speeky helps you practice interviews, meetings, presentations, and difficult
            conversations out loud, with feedback that feels useful instead of judgmental.
          </p>

          <div className="mt-9 flex animate-fade-up flex-col gap-4 sm:flex-row">
            <Button
              size="lg"
              className="gap-2 bg-accent text-accent-foreground shadow-md shadow-accent/15 hover:bg-accent-hover"
              href="/signup"
            >
              Start Practicing
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button size="lg" variant="outline" className="gap-2 bg-surface/70" href="#how-it-works">
              <PlayCircle className="h-4 w-4" aria-hidden="true" />
              See How It Works
            </Button>
          </div>

          <div className="mt-12 grid w-full grid-cols-2 gap-4 sm:grid-cols-4">
            {HERO_FEATURES.map(({ label, icon: Icon, tone }) => (
              <div key={label} className="flex flex-col gap-3 text-sm text-foreground">
                <span className={`flex h-10 w-10 items-center justify-center rounded-2xl ${tone}`}>
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <span className="max-w-[9rem] leading-snug">{label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="relative hidden min-h-[34rem] lg:block">
          <div className="absolute inset-x-4 bottom-5 h-28 rounded-full bg-primary/12 blur-3xl" aria-hidden="true" />




          <div className="absolute inset-y-8 right-0 w-[84%] overflow-visible rounded-[2.25rem] border border-border/70 bg-surface-elevated/72 shadow-[0_24px_80px_hsl(var(--foreground)/0.08)] backdrop-blur-sm dark:bg-surface-elevated/45">
            <div className="absolute inset-0 rounded-[2.25rem] bg-[radial-gradient(circle_at_76%_28%,hsl(var(--primary)/0.12),transparent_28%),radial-gradient(circle_at_88%_88%,hsl(var(--accent)/0.16),transparent_34%),linear-gradient(135deg,hsl(var(--surface-elevated)/0.68)_0%,hsl(var(--secondary)/0.34)_100%)] dark:bg-[radial-gradient(circle_at_76%_28%,hsl(var(--danger)/0.13),transparent_28%),radial-gradient(circle_at_88%_88%,hsl(var(--accent)/0.14),transparent_34%),linear-gradient(135deg,hsl(var(--surface-elevated)/0.55)_0%,hsl(var(--secondary)/0.22)_100%)]" />
            <div className="absolute bottom-[-4.5rem] right-[-3rem] h-64 w-64 rounded-full bg-accent/12 blur-sm" />
            <div className="absolute bottom-2 left-14 right-8 h-20 rounded-[100%] bg-warning/10 blur-md" />
            <Image
              src="/speeky-hero-coach-cutout-soft.png"
              alt="Speeky AI communication coach"
              width={720}
              height={720}
              priority
              className="absolute bottom-[-1.25rem] right-[-1.25rem] h-[33rem] w-auto object-contain drop-shadow-[0_26px_38px_hsl(var(--foreground)/0.16)] dark:hidden"
            />
            <Image
              src="/speeky-hero-coach-red-cutout-soft.png"
              alt="Speeky AI communication coach"
              width={720}
              height={720}
              priority
              className="absolute bottom-[-1.25rem] right-[-1.25rem] hidden h-[33rem] w-auto object-contain drop-shadow-[0_26px_38px_hsl(var(--foreground)/0.24)] dark:block"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-2 text-sm text-muted-foreground lg:col-span-2">
          {TRUST_INDICATORS.map((item) => (
            <span key={item.id} className="inline-flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
              {item.label}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
