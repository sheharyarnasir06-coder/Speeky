import { SectionTitle } from "@/components/common/SectionTitle";
import { HOW_IT_WORKS } from "@/lib/mock-data";

/**
 * Step-by-step timeline. Numbering is meaningful here since the steps
 * are a real, ordered onboarding flow (not decorative 01/02/03 markers).
 */
export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-[2rem] border border-border bg-surface/80 px-5 py-12 shadow-[0_22px_70px_hsl(var(--foreground)/0.07)] backdrop-blur sm:px-8 lg:px-10">
          <div
            aria-hidden="true"
            className="absolute -left-10 bottom-8 h-36 w-36 rounded-full bg-primary/10"
          />
          <div
            aria-hidden="true"
            className="absolute -right-8 top-10 h-44 w-44 rounded-full bg-accent/10"
          />
          <div className="relative grid gap-12 lg:grid-cols-[0.85fr_1.15fr] lg:items-center">
            <SectionTitle
              align="left"
              eyebrow="How It Works"
              title="From first conversation to real confidence"
              description="A simple path from sign-up to assessment, practice, progress tracking, and real-world confidence."
            />

            <ol className="relative flex w-full flex-col gap-4 rounded-3xl border border-border bg-surface-elevated p-5 shadow-sm sm:p-6">
              {HOW_IT_WORKS.map((step, index) => (
                <li
                  key={step.id}
                  className="group relative grid gap-4 rounded-2xl border border-border bg-surface px-4 py-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm sm:grid-cols-[3rem_1fr]"
                >
                  <span
                    className={[
                      "flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white shadow-sm",
                      index === 0 && "bg-accent",
                      index === 1 && "bg-danger",
                      index === 2 && "bg-primary",
                      index === 3 && "bg-violet-500",
                      index === 4 && "bg-warning",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {step.index}
                  </span>
                  <div className="flex flex-col gap-1">
                    <h3 className="font-semibold text-foreground">
                      {step.title}
                    </h3>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {step.description}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}
