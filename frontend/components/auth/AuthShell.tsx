"use client";

import * as React from "react";
import Link from "next/link";
import Image from "next/image";
import { ArrowLeft } from "lucide-react";
import { LegalModal } from "@/components/common/LegalModal";
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
    <div className="relative flex min-h-screen animate-fade-up flex-col items-center justify-center overflow-hidden bg-background px-4 py-3 sm:py-6 lg:flex-row lg:px-8">
      <div className="relative grid w-full max-w-[88rem] overflow-hidden rounded-[1.75rem] border border-border bg-surface-elevated shadow-[0_24px_80px_hsl(var(--foreground)/0.10)] lg:grid-cols-[1.08fr_0.92fr]">
        <Link
          href="/"
          className="absolute left-5 top-5 z-30 inline-flex items-center gap-2 rounded-full border border-border bg-surface/75 px-3 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur transition-colors duration-fast hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Back to home
        </Link>
        <div className="relative hidden min-h-[40rem] flex-col overflow-hidden border-r border-border bg-surface px-12 py-8 lg:flex">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-[-6.5rem] top-14 h-56 w-56 rounded-br-[6rem] rounded-tr-[6rem] bg-accent/8 dark:hidden"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-[-4rem] left-[-3rem] h-40 w-40 rounded-full bg-danger/55 blur-[1px] dark:hidden"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-[-3.5rem] right-[-3rem] h-44 w-44 rounded-full bg-primary/22 blur-[1px] dark:bg-primary/14"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-24 top-24 h-20 w-20 rounded-full bg-secondary/70 blur-2xl dark:hidden"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-24 bottom-28 h-24 w-24 rounded-full bg-primary/10 blur-2xl dark:hidden"
        />

        <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-8 pt-8 text-center">
          <Link href="/" className="inline-flex items-center">
            <Image
              src="/speeky-consolidated-logo.png"
              alt="Speeky"
              width={277}
              height={100}
              className="speeky-logo-heartbeat h-24 w-auto dark:brightness-0 dark:invert"
              priority
            />
          </Link>

          <div
            className={cn(
              "flex max-w-md flex-col items-center gap-4 transition-opacity duration-500 ease-in-out",
              fade ? "opacity-100" : "opacity-0",
            )}
          >
            <p className="font-serif text-2xl leading-snug text-foreground xl:text-3xl">
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

      <div className="relative flex min-h-[40rem] w-full flex-col justify-center overflow-hidden bg-surface-elevated px-6 py-10 sm:px-12 lg:px-14">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-[-8rem] top-[-8rem] h-72 w-72 rounded-full bg-secondary blur-3xl dark:hidden"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-[-6rem] bottom-[-6rem] h-56 w-56 rounded-full bg-primary/12 blur-3xl dark:hidden"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-10 top-24 h-20 w-20 rounded-full bg-danger/10 blur-2xl dark:hidden"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-[-7rem] top-[-7rem] hidden h-72 w-72 rounded-full bg-primary/10 blur-3xl dark:block"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-8 top-8 hidden items-center gap-2 lg:flex"
        >
          <span className="h-2 w-2 rounded-full bg-primary/45" />
          <span className="h-2 w-2 rounded-full bg-accent/45" />
          <span className="h-2 w-2 rounded-full bg-danger/45" />
        </div>
        <div className="relative mx-auto flex w-full max-w-sm flex-col gap-6">
          <div className="relative -mx-2 flex flex-col items-center gap-3 overflow-hidden rounded-2xl border border-border bg-surface px-5 pb-5 pt-6 text-center lg:hidden">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute left-[-3rem] top-[-3rem] h-40 w-40 rounded-full bg-primary/15 blur-2xl dark:bg-accent/15"
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute bottom-[-3.5rem] right-[-3rem] h-40 w-40 rounded-full bg-accent/15 blur-2xl dark:bg-primary/15"
            />
            <Link href="/" className="relative inline-flex items-center">
              <Image
                src="/speeky-consolidated-logo.png"
                alt="Speeky"
                width={277}
                height={100}
                className="speeky-logo-heartbeat h-11 w-auto dark:brightness-0 dark:invert"
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
      </div>

      <LegalModal type={legalType} open={legalType !== null} onClose={() => setLegalType(null)} />
    </div>
  );
}
