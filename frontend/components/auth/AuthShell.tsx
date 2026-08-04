"use client";

import * as React from "react";
import Link from "next/link";
import Image from "next/image";
import { ArrowLeft } from "lucide-react";
import { LegalModal } from "@/components/common/LegalModal";
import { VoiceWave } from "@/components/common/VoiceWave";
import { TESTIMONIALS } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface AuthShellProps {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
  legalNote?: ReactNode;
}

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
  footer,
  legalNote,
}: AuthShellProps) {
  const [quoteIndex, setQuoteIndex] = React.useState(0);
  const [fade, setFade] = React.useState(true);
  const [legalType, setLegalType] = React.useState<"terms" | "privacy" | null>(
    null,
  );

  React.useEffect(() => {
    const interval = window.setInterval(() => {
      setFade(false);
      window.setTimeout(() => {
        setQuoteIndex((prev) => (prev + 1) % TESTIMONIALS.length);
        setFade(true);
      }, 350);
    }, 8000);

    return () => window.clearInterval(interval);
  }, []);

  const currentQuote = TESTIMONIALS[quoteIndex];

  const defaultLegalNote = (
    <p>
      By continuing you agree to Speeky&apos;s{" "}
      <button
        type="button"
        onClick={() => setLegalType("terms")}
        className="font-medium text-foreground hover:text-primary"
      >
        Terms
      </button>{" "}
      and{" "}
      <button
        type="button"
        onClick={() => setLegalType("privacy")}
        className="font-medium text-foreground hover:text-primary"
      >
        Privacy Policy
      </button>
      .
    </p>
  );

  return (
    <div className="relative flex min-h-screen animate-fade-up flex-col overflow-hidden bg-background lg:flex-row">
      <Link
        href="/"
        // opacity-60 on already-muted text measured 2.24:1 (light) / 3.06:1 (dark) —
        // well under AA. Full-strength muted text with a hover shift to foreground
        // keeps the same recessive feel while staying legible.
        className="absolute left-5 top-5 z-20 inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur transition-colors duration-fast hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to home
      </Link>

      <div className="relative hidden flex-col overflow-hidden border-r border-border bg-surface px-12 py-10 lg:flex lg:w-1/2">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-[-8rem] top-10 h-72 w-72 rounded-full bg-primary/10 blur-3xl dark:bg-accent/10"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-[-10rem] right-[-10rem] h-96 w-96 rounded-full bg-accent/10 blur-3xl dark:bg-primary/10"
        />
        <VoiceWave compact className="bottom-24 opacity-35 dark:opacity-45" />

        <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-10 text-center">
          <Link href="/" className="inline-flex items-center">
            <Image
              src="/logo-full.png"
              alt="Speeky"
              width={213}
              height={239}
              className="h-24 w-auto dark:brightness-0 dark:invert"
              priority
            />
          </Link>

          <div
            className={cn(
              "flex max-w-md flex-col items-center gap-4 transition-opacity duration-500 ease-in-out",
              fade ? "opacity-100" : "opacity-0",
            )}
          >
            <p className="font-serif text-3xl leading-snug text-foreground">
              &ldquo;{currentQuote.quote}&rdquo;
            </p>
            <p className="text-sm text-muted-foreground">
              {currentQuote.name} &middot; {currentQuote.role}
            </p>
          </div>
        </div>

        <p className="relative z-10 text-center text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} Speeky. Built for Mazik Global.
        </p>
      </div>

      <div className="relative flex w-full flex-1 flex-col justify-center px-6 py-20 sm:px-12 lg:w-1/2 lg:px-16">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-[-8rem] top-[-8rem] h-72 w-72 rounded-full bg-secondary blur-3xl dark:bg-accent/10"
        />
        <div className="relative mx-auto flex w-full max-w-sm flex-col gap-8">
          {/* Below `lg` the two-column split has no room, so instead of just
              hiding the branding panel (a blank first impression on the
              devices most of this audience actually signs up on — see
              planning notes on the Pakistan/South Asia mobile-first market)
              this is a compact standalone band: same glow + voice-wave + one
              rotating testimonial line, sized for a phone instead of half a
              desktop viewport. */}
          <div className="relative -mx-2 flex flex-col items-center gap-3 overflow-hidden rounded-2xl border border-border bg-surface px-5 pb-5 pt-6 text-center lg:hidden">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute left-[-3rem] top-[-3rem] h-40 w-40 rounded-full bg-primary/15 blur-2xl dark:bg-accent/15"
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute bottom-[-3.5rem] right-[-3rem] h-40 w-40 rounded-full bg-accent/15 blur-2xl dark:bg-primary/15"
            />
            <VoiceWave compact className="bottom-0 h-16 opacity-30 dark:opacity-40" />

            <Link href="/" className="relative inline-flex items-center">
              <Image
                src="/logo-full.png"
                alt="Speeky"
                width={142}
                height={159}
                className="h-9 w-auto dark:brightness-0 dark:invert"
                priority
              />
            </Link>

            <div
              className={cn(
                "relative flex max-w-xs flex-col gap-1 transition-opacity duration-500 ease-in-out",
                fade ? "opacity-100" : "opacity-0",
              )}
            >
              <p className="font-serif text-sm leading-snug text-foreground">
                &ldquo;{currentQuote.quote}&rdquo;
              </p>
              <p className="text-xs text-muted-foreground">
                {currentQuote.name} &middot; {currentQuote.role}
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-primary">{eyebrow}</span>
            <h1 className="font-serif text-h1 font-semibold text-foreground">
              {title}
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">{description}</p>
          </div>

          {children}

          <div className="text-center text-sm text-muted-foreground">{footer}</div>

          <div className="text-center text-xs leading-5 text-muted-foreground">
            {legalNote ?? defaultLegalNote}
          </div>
        </div>
      </div>

      <LegalModal type={legalType} open={legalType !== null} onClose={() => setLegalType(null)} />
    </div>
  );
}
