import { Check, X } from "lucide-react";
import { SectionTitle } from "@/components/common/SectionTitle";
import { COMPARISON_POINTS } from "@/lib/mock-data";

/**
 * Explains the core philosophy: confidence over grammar. Contrasts
 * traditional English learning with AI conversation coaching using
 * a simple two-column comparison.
 */
export function WhySpeeky() {
  return (
    <section id="why-speeky" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-[2rem] border border-border bg-surface/80 px-5 py-12 shadow-[0_22px_70px_hsl(var(--foreground)/0.07)] backdrop-blur sm:px-8 lg:px-10">
          <div
            aria-hidden="true"
            className="absolute -left-16 top-16 h-44 w-44 rounded-br-[6rem] rounded-tr-[6rem] bg-secondary/80"
          />
          <div
            aria-hidden="true"
            className="absolute -right-16 bottom-10 h-48 w-48 rounded-full bg-danger/10"
          />

          <div className="relative flex flex-col gap-12">
            <SectionTitle
              eyebrow="Why Speeky"
              title="Confidence matters more than grammar"
              description="Most people preparing for interviews and workplace conversations already know the grammar. What holds them back is speaking up, staying fluent under pressure, and sounding confident in the moment."
            />

            <div className="mx-auto grid w-full max-w-5xl overflow-hidden rounded-3xl border border-border bg-surface-elevated shadow-sm sm:grid-cols-2">
              <div className="flex flex-col gap-5 border-b border-border bg-danger/5 p-7 sm:border-b-0 sm:border-r lg:p-8">
                <span className="text-sm font-semibold text-danger">
                  Traditional English Learning
                </span>
                <ul className="flex flex-col gap-4">
                  {COMPARISON_POINTS.map((point) => (
                    <li key={point.id} className="flex items-start gap-3 text-sm text-muted-foreground">
                      <X className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
                      {point.traditional}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="flex flex-col gap-5 bg-accent/5 p-7 lg:p-8">
                <span className="text-sm font-semibold text-accent">
                  Speeky AI Coaching
                </span>
                <ul className="flex flex-col gap-4">
                  {COMPARISON_POINTS.map((point) => (
                    <li key={point.id} className="flex items-start gap-3 text-sm text-foreground">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
                      {point.speeky}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
