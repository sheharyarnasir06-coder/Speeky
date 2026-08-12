import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CTASection() {
  return (
    <section id="cta" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-[2rem] border border-border bg-surface/85 px-8 py-16 text-center shadow-[0_22px_70px_hsl(var(--foreground)/0.08)] backdrop-blur sm:px-16">
          <div
            aria-hidden="true"
            className="absolute -left-10 bottom-0 h-36 w-36 rounded-full bg-danger/55 dark:bg-danger/25"
          />
          <div
            aria-hidden="true"
            className="absolute -right-12 top-8 h-44 w-44 rounded-full bg-accent/14"
          />
          <div
            aria-hidden="true"
            className="absolute left-1/2 top-0 h-px w-40 -translate-x-1/2 bg-gradient-to-r from-transparent via-accent/50 to-transparent"
          />
          <div className="relative">
            <span className="text-sm font-semibold text-accent">Ready when you are</span>
            <h2 className="mx-auto mt-3 max-w-3xl text-balance font-serif text-h1 font-semibold text-foreground sm:text-4xl">
              Practice today. Speak tomorrow with confidence.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-balance text-base text-muted-foreground sm:text-lg">
              Your next interview, meeting, or conversation deserves your best
              English. Practice with Speeky and walk in ready.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Button
                size="lg"
                className="gap-2 bg-accent text-accent-foreground shadow-md shadow-accent/15 hover:bg-accent-hover"
                href="/signup"
              >
                Get Started Free
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button size="lg" variant="outline" className="bg-surface-elevated/80" href="/login">
                Login
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
