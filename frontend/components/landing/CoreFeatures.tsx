import { SectionTitle } from "@/components/common/SectionTitle";
import { FeatureCard } from "@/components/landing/FeatureCard";
import { CORE_FEATURES } from "@/lib/mock-data";
import { ScrollReveal } from "@/components/ui/scroll-reveal"; // 1. Import the new component

export function CoreFeatures() {
  return (
    <section id="features" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-[2rem] border border-border bg-surface/80 px-5 py-12 shadow-[0_22px_70px_hsl(var(--foreground)/0.07)] backdrop-blur sm:px-8 lg:px-10">
          <div
            aria-hidden="true"
            className="absolute -left-12 top-10 h-40 w-40 rounded-full bg-primary/8"
          />
          <div
            aria-hidden="true"
            className="absolute -right-10 bottom-8 h-44 w-44 rounded-full bg-accent/10"
          />
          <div className="relative flex flex-col gap-12">
            <SectionTitle
              eyebrow="Core Features"
              title="Everything you need to communicate with confidence"
              description="Speeky combines conversation practice, interview coaching, and workplace scenarios into one AI-powered coach."
            />

            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {CORE_FEATURES.map((feature, index) => (
                <ScrollReveal key={feature.id} delay={index * 100}>
                  <FeatureCard feature={feature} />
                </ScrollReveal>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
