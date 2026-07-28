import * as React from "react";
import { cn } from "@/lib/utils";

type CardElevation = "flat" | "raised" | "floating";

type CardTag = "div" | "section" | "article" | "li";

interface CardProps extends React.HTMLAttributes<HTMLElement> {
  /** flat = inside another surface · raised = default page card · floating = overlay/emphasis */
  elevation?: CardElevation;
  /** Lift + shadow on hover. Only for cards that are actually clickable. */
  interactive?: boolean;
  /** Semantic element — use `section`/`article`/`li` so the DOM reflects meaning. */
  as?: CardTag;
}

const elevationClasses: Record<CardElevation, string> = {
  flat: "bg-surface shadow-none",
  raised: "bg-surface-elevated shadow-sm",
  floating: "bg-surface-elevated shadow-lg",
};

/**
 * The single card surface for the whole product.
 *
 * Replaces the hand-written `rounded-2xl border border-border bg-surface-elevated
 * p-6 shadow-sm` string that had been copied into ~50 files, where radius, padding
 * and shadow had already drifted apart. One component means one visual language and
 * one place to change it.
 */
export function Card({
  elevation = "raised",
  interactive = false,
  as: Tag = "div",
  className,
  ...props
}: CardProps) {
  const Element = Tag as React.ElementType;
  return (
    <Element
      className={cn(
        "rounded-2xl border border-border",
        elevationClasses[elevation],
        interactive &&
          "cursor-pointer transition-[transform,box-shadow,border-color] duration-normal ease-out-expo " +
            "hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-lg " +
            "focus-within:border-primary/40 active:translate-y-0 motion-reduce:hover:translate-y-0",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-6 pb-0", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("font-serif text-h3 text-foreground", className)}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-6", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex items-center gap-3 border-t border-border p-6 pt-4", className)}
      {...props}
    />
  );
}
