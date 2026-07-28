import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CTASection() {
  return (
    <section id="cta" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-2xl border border-border bg-[radial-gradient(80%_120%_at_50%_0%,hsl(var(--secondary))_0%,hsl(var(--surface))_100%)] px-8 py-16 text-center shadow-sm sm:px-16">
          <h2 className="text-balance font-serif text-h1 font-semibold text-foreground sm:text-4xl">
            Start speaking with confidence today
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-balance text-base text-muted-foreground sm:text-lg">
            Your next interview, meeting, or conversation deserves your best
            English. Practice with Speeky and walk in ready.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Button size="lg" className="gap-2" href="/signup">
              Get Started Free
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button size="lg" variant="outline" href="/login">
              Login
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
