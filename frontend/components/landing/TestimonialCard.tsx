import { Quote } from "lucide-react";
import type { Testimonial } from "@/lib/types";

interface TestimonialCardProps {
  testimonial: Testimonial;
}

export function TestimonialCard({ testimonial }: TestimonialCardProps) {
  const { name, role, quote, initials } = testimonial;

  return (
    <figure className="group flex h-full flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:shadow-[0_18px_45px_hsl(var(--foreground)/0.08)]">
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-secondary text-primary transition-colors group-hover:bg-primary group-hover:text-white">
        <Quote className="h-4 w-4" aria-hidden="true" />
      </span>
      <blockquote className="flex-1 text-sm leading-relaxed text-foreground">
        &ldquo;{quote}&rdquo;
      </blockquote>
      <figcaption className="flex items-center gap-3">
        <span
          className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-sm font-semibold text-accent"
          aria-hidden="true"
        >
          {initials}
        </span>
        <div className="flex flex-col">
          <span className="text-sm font-medium text-foreground">{name}</span>
          <span className="text-xs text-muted-foreground">{role}</span>
        </div>
      </figcaption>
    </figure>
  );
}
