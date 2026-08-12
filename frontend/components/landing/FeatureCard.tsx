import type { FeatureItem } from "@/lib/types";

interface FeatureCardProps {
  feature: FeatureItem;
}

/**
 * Single reusable card for a product feature. Used across Core Features
 * and can be reused anywhere else a feature needs to be presented.
 */
export function FeatureCard({ feature }: FeatureCardProps) {
  const { icon: Icon, title, description } = feature;

  return (
    <div className="group relative flex min-h-[13rem] flex-col gap-4 overflow-hidden rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:shadow-[0_18px_45px_hsl(var(--foreground)/0.08)]">
      <span
        aria-hidden="true"
        className="absolute -right-10 -top-10 h-28 w-28 rounded-full bg-accent/8 transition-transform duration-300 group-hover:scale-125"
      />
      <div className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary transition-colors group-hover:bg-primary group-hover:text-white">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <h3 className="relative font-serif text-lg font-semibold text-foreground">{title}</h3>
      <p className="relative text-sm leading-relaxed text-muted-foreground">
        {description}
      </p>
    </div>
  );
}
