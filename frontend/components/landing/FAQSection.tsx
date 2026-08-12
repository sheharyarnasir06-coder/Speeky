import { SectionTitle } from "@/components/common/SectionTitle";
import { Accordion } from "@/components/ui/accordion";
import { FAQ_ITEMS } from "@/lib/mock-data";

export function FAQSection() {
  const items = FAQ_ITEMS.map((item) => ({
    id: item.id,
    trigger: item.question,
    content: item.answer,
  }));

  return (
    <section id="faq" className="py-24">
      <div className="container">
        <div className="relative overflow-hidden rounded-[2rem] border border-border bg-surface/80 px-5 py-12 shadow-[0_22px_70px_hsl(var(--foreground)/0.07)] backdrop-blur sm:px-8 lg:px-10">
          <div
            aria-hidden="true"
            className="absolute -right-12 top-10 h-44 w-44 rounded-full bg-primary/10"
          />
          <div className="relative flex flex-col gap-12">
            <SectionTitle eyebrow="FAQ" title="Common questions" />

            <div className="mx-auto w-full max-w-3xl">
              <Accordion items={items} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
