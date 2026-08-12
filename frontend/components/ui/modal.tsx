"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  hideCloseButton?: boolean;
}

/**
 * Portal-based modal — backdrop click / Escape to close, locks body scroll
 * while open, animates in/out (kept mounted briefly after close so the
 * exit transition can play instead of snapping shut).
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  className,
  hideCloseButton,
}: ModalProps) {
  const [canPortal, setCanPortal] = React.useState(false);
  const [rendered, setRendered] = React.useState(open);
  const [entered, setEntered] = React.useState(false);
  const dialogRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => setCanPortal(true), []);

  React.useEffect(() => {
    if (open) {
      setRendered(true);
      const raf = requestAnimationFrame(() => setEntered(true));
      return () => cancelAnimationFrame(raf);
    }
    setEntered(false);
    const timeout = setTimeout(() => setRendered(false), 200);
    return () => clearTimeout(timeout);
  }, [open]);

  // Callers rarely memoize onClose (e.g. inline `() => setOpen(false)`), so
  // it's a fresh function on every parent render — which, for a controlled
  // form inside the modal, means every keystroke. Reading it via a ref keeps
  // this effect keyed on `open` alone: it fires once per open/close instead
  // of on every parent re-render, which matters because it also steals
  // focus back to the first field — re-running it mid-typing was yanking
  // focus (and the cursor) back to that first field on every keystroke.
  const onCloseRef = React.useRef(onClose);
  React.useEffect(() => {
    onCloseRef.current = onClose;
  });

  React.useEffect(() => {
    if (!open) return;

    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", handleKey);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const firstField = dialogRef.current?.querySelector<HTMLElement>(
      "input, button:not([aria-label='Close'])",
    );
    firstField?.focus();

    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!canPortal || !rendered) return null;

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
      <div
        className={cn(
          "absolute inset-0 bg-foreground/40 backdrop-blur-sm transition-opacity duration-200",
          entered ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className={cn(
          "relative flex max-h-[80dvh] w-full max-w-2xl flex-col rounded-2xl border border-border bg-surface-elevated shadow-lg transition-all duration-200",
          entered
            ? "translate-y-0 scale-100 opacity-100"
            : "translate-y-2 scale-95 opacity-0",
          className,
        )}
      >
        <div className="relative shrink-0 p-6 pb-4">
          {!hideCloseButton && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="absolute right-4 top-4 rounded-lg p-1 text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}

          <h2
            id="modal-title"
            className={cn(
              "font-serif text-lg font-semibold",
              !hideCloseButton && "pr-8",
            )}
          >
            {title}
          </h2>

          {description && (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
