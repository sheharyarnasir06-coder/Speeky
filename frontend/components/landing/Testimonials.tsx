import { SectionTitle } from "@/components/common/SectionTitle";
import { TestimonialCard } from "@/components/landing/TestimonialCard";
import { TESTIMONIALS } from "@/lib/mock-data";

export function Testimonials() {
  return (
    <section id="testimonials" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-[2rem] border border-border bg-surface/80 px-5 py-12 shadow-[0_22px_70px_hsl(var(--foreground)/0.07)] backdrop-blur sm:px-8 lg:px-10">
          <div
            aria-hidden="true"
            className="absolute -left-12 top-12 h-36 w-36 rounded-full bg-accent/10"
          />
          <div
            aria-hidden="true"
            className="absolute -right-12 bottom-10 h-44 w-44 rounded-full bg-primary/10"
          />
          <div className="relative flex flex-col gap-12">
            <SectionTitle
              eyebrow="Testimonials"
              title="Trusted by students, job seekers, and professionals"
            />

            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {TESTIMONIALS.map((testimonial) => (
                <TestimonialCard key={testimonial.id} testimonial={testimonial} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
