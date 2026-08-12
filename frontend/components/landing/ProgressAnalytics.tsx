import { SectionTitle } from "@/components/common/SectionTitle";
import { StatsCard } from "@/components/landing/StatsCard";
import { PROGRESS_STATS } from "@/lib/mock-data";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"];

const SKILLS = [
  { label: "Fluency", value: "68%", color: "bg-primary" },
  { label: "Confidence", value: "82%", color: "bg-accent" },
  { label: "Pronunciation", value: "71%", color: "bg-danger" },
  { label: "Vocabulary", value: "64%", color: "bg-warning" },
];

export function ProgressAnalytics() {
  return (
    <section className="py-24">
      <div className="container flex flex-col gap-10">
        <SectionTitle
          eyebrow="Progress & Analytics"
          title="Growth you can actually see"
          description="Every session updates your dashboard, so progress feels measurable instead of assumed. This is illustrative sample data."
        />

        <div className="mx-auto w-full max-w-6xl rounded-[2rem] border border-border bg-surface/80 p-4 shadow-[0_22px_70px_hsl(var(--foreground)/0.08)] backdrop-blur sm:p-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {PROGRESS_STATS.map((stat) => (
              <StatsCard key={stat.id} stat={stat} />
            ))}
          </div>

          <div className="mt-5 grid gap-5 lg:grid-cols-[1.45fr_0.8fr]">
            <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
              <div className="mb-5 flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">
                    Speaking Progress Over Time
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Sample monthly confidence trend
                  </p>
                </div>
                <span className="rounded-full bg-accent/10 px-3 py-1 text-xs font-semibold text-accent">
                  68% this month
                </span>
              </div>

              <div className="relative h-52 overflow-hidden rounded-xl bg-[linear-gradient(180deg,hsl(var(--muted)/0.45),transparent)] px-3 pb-8 pt-3">
                <div className="absolute inset-x-3 bottom-8 top-3 grid grid-rows-4">
                  {["100%", "75%", "50%", "25%"].map((label) => (
                    <div key={label} className="relative border-t border-border/70">
                      <span className="absolute -top-2 left-0 bg-surface-elevated pr-2 text-[10px] text-muted-foreground">
                        {label}
                      </span>
                    </div>
                  ))}
                </div>

                <svg
                  viewBox="0 0 620 190"
                  className="absolute inset-x-8 bottom-8 top-5 h-[150px] w-[calc(100%-4rem)] overflow-visible"
                  role="img"
                  aria-label="Speaking progress rising from January to June"
                >
                  <defs>
                    <linearGradient id="speaking-progress-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity="0.22" />
                      <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  <path
                    d="M0 155 L92 125 L185 133 L278 95 L371 108 L464 62 L558 46 L620 30 L620 190 L0 190 Z"
                    fill="url(#speaking-progress-fill)"
                  />
                  <path
                    d="M0 155 C40 144 58 134 92 125 C126 116 151 141 185 133 C224 124 241 101 278 95 C313 90 336 113 371 108 C414 103 425 70 464 62 C503 54 521 49 558 46 C584 43 602 34 620 30"
                    fill="none"
                    stroke="hsl(var(--accent))"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="7"
                  />
                  {[0, 92, 185, 278, 371, 464, 558, 620].map((x, index) => {
                    const y = [155, 125, 133, 95, 108, 62, 46, 30][index];
                    return (
                      <circle
                        key={x}
                        cx={x}
                        cy={y}
                        r="8"
                        fill="hsl(var(--surface-elevated))"
                        stroke="hsl(var(--accent))"
                        strokeWidth="5"
                      />
                    );
                  })}
                </svg>

                <div className="absolute inset-x-8 bottom-2 grid grid-cols-6 text-center text-[11px] text-muted-foreground">
                  {MONTHS.map((month) => (
                    <span key={month}>{month}</span>
                  ))}
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-foreground">Skills Breakdown</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Where the latest score comes from
              </p>

              <div className="mt-5 flex flex-col items-center gap-5 sm:flex-row lg:flex-col xl:flex-row">
                <div className="relative h-36 w-36 shrink-0 rounded-full bg-[conic-gradient(hsl(var(--primary))_0_32%,hsl(var(--accent))_32%_58%,hsl(var(--danger))_58%_78%,hsl(var(--warning))_78%_100%)] shadow-inner">
                  <div className="absolute inset-6 rounded-full bg-surface-elevated" />
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-2xl font-semibold text-foreground">68%</span>
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Overall
                    </span>
                  </div>
                </div>

                <div className="grid w-full gap-3">
                  {SKILLS.map((skill) => (
                    <div key={skill.label} className="flex items-center justify-between gap-3 text-sm">
                      <span className="flex items-center gap-2 text-muted-foreground">
                        <span className={`h-2.5 w-2.5 rounded-full ${skill.color}`} />
                        {skill.label}
                      </span>
                      <span className="font-semibold text-foreground">{skill.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
