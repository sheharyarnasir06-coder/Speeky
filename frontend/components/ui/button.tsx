import * as React from "react";
import Link, { type LinkProps } from "next/link";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

interface SharedProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: React.ReactNode;
  loading?: boolean;
}

type ButtonAsButton = SharedProps &
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
    href?: undefined;
  };

type ButtonAsLink = SharedProps &
  Omit<LinkProps, "className"> &
  Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "className" | "href"> & {
    href: LinkProps["href"];
  };

export type ButtonProps = ButtonAsButton | ButtonAsLink;

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary-hover",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  outline:
    "border border-border bg-transparent text-foreground hover:bg-surface",
  ghost: "bg-transparent text-foreground hover:bg-surface",
  // White, not --primary-foreground: that token is near-black in dark mode and
  // rendered 3.89:1 on the red fill (AA needs 4.5:1). The danger fill is a saturated
  // red in both themes, so white is correct in both — no theme-dependent token needed.
  danger: "bg-danger text-white hover:bg-danger/90",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-9 px-4 text-sm",
  md: "h-10 px-5 text-sm",
  lg: "h-12 px-6 text-base",
};

const baseClasses =
  "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 disabled:active:scale-100";

function Spinner() {
  return (
    <span
      className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
      aria-hidden="true"
    />
  );
}

/**
 * Custom Button primitive — supports the constitution's approved variants
 * (Primary, Secondary, Outline, Ghost, Danger) plus Loading/Disabled states.
 * Renders a Next.js <Link> when `href` is passed, otherwise a native
 * <button>. No shadcn/ui or Radix dependency.
 */
export function Button(props: ButtonProps) {
  const { variant = "primary", size = "md", className, children, loading } =
    props;
  const classes = cn(
    baseClasses,
    variantClasses[variant],
    sizeClasses[size],
    className,
  );

  if (props.href !== undefined) {
    const { href, variant: _v, size: _s, className: _c, loading: _l, children: _ch, ...rest } =
      props as ButtonAsLink;
    return (
      <Link href={href} className={classes} {...rest}>
        {loading ? <Spinner /> : children}
      </Link>
    );
  }

  const { variant: _v2, size: _s2, className: _c2, loading: _l2, children: _ch2, ...rest } =
    props as ButtonAsButton;
  return (
    <button
      className={classes}
      disabled={rest.disabled || loading}
      {...rest}
    >
      {loading ? <Spinner /> : children}
    </button>
  );
}
