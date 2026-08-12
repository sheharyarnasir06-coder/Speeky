import Link from "next/link";
import Image from "next/image";
import { ArrowLeft } from "lucide-react";

interface LegalSection {
  id: string;
  title: string;
  paragraphs?: string[];
  bullets?: string[];
  closingParagraphs?: string[];
}

interface LegalDocumentProps {
  title: string;
  version: string;
  effectiveDate: string;
  sections: LegalSection[];
  backHref: string;
  backLabel: string;
}

/**
 * Shared shell for /terms and /privacy — header, table of contents, and
 * numbered sections. Sections with an empty title are treated as a
 * continuation of the previous section (e.g. a bullet list split across
 * two data entries) and excluded from the table of contents.
 */
export function LegalDocument({
  title,
  version,
  effectiveDate,
  sections,
  backHref,
  backLabel,
}: LegalDocumentProps) {
  const tocEntries = sections.filter((section) => section.title);

  return (
    <div className="min-h-screen bg-surface">
      <header className="border-b border-border bg-background">
        <div className="container flex h-16 items-center justify-between">
          <Link href="/" className="flex items-center" aria-label="Speeky home">
            <Image
              src="/speeky-consolidated-logo.png"
              alt="Speeky"
              width={277}
              height={100}
              className="speeky-logo-heartbeat h-11 w-auto dark:brightness-0 dark:invert"
            />
          </Link>
          <Link
            href={backHref}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {backLabel}
          </Link>
        </div>
      </header>

      <main className="container py-16">
        <div className="mx-auto flex max-w-2xl flex-col gap-10">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-primary">{version}</span>
            <h1 className="font-serif text-4xl font-semibold tracking-tight text-foreground">
              {title}
            </h1>
            <p className="text-sm text-muted-foreground">
              Effective Date: {effectiveDate}
            </p>
          </div>

          <nav
            aria-label="Table of contents"
            className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm"
          >
            <p className="text-sm font-semibold text-foreground">On this page</p>
            <ul className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
              {tocEntries.map((section) => (
                <li key={section.id}>
                  <a
                    href={`#${section.id}`}
                    className="text-sm text-muted-foreground transition-colors hover:text-primary"
                  >
                    {section.title}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <div className="flex flex-col gap-10 rounded-2xl border border-border bg-surface-elevated p-8 shadow-sm sm:p-10">
            {sections.map((section) => (
              <section
                key={section.id}
                id={section.id}
                className="flex scroll-mt-8 flex-col gap-3"
              >
                {section.title ? (
                  <h2 className="font-serif text-xl font-semibold text-foreground">
                    {section.title}
                  </h2>
                ) : null}

                {section.paragraphs?.map((paragraph, index) => (
                  <p
                    key={`${section.id}-p-${index}`}
                    className="text-sm leading-relaxed text-muted-foreground"
                  >
                    {paragraph}
                  </p>
                ))}

                {section.bullets ? (
                  <ul className="flex flex-col gap-2 pl-1">
                    {section.bullets.map((bullet, index) => (
                      <li
                        key={`${section.id}-b-${index}`}
                        className="flex items-start gap-2.5 text-sm leading-relaxed text-muted-foreground"
                      >
                        <span
                          className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground"
                          aria-hidden="true"
                        />
                        {bullet}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {section.closingParagraphs?.map((paragraph, index) => (
                  <p
                    key={`${section.id}-cp-${index}`}
                    className="text-sm leading-relaxed text-muted-foreground"
                  >
                    {paragraph}
                  </p>
                ))}
              </section>
            ))}

            <p className="border-t border-border pt-6 text-center text-xs text-muted-foreground">
              &copy; {new Date().getFullYear()} Speeky. All Rights Reserved.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
