"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Catches render/runtime errors anywhere under the root layout so a bug in
 * one page shows a recoverable screen instead of a blank white crash.
 */
export default function GlobalErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-danger/10 text-danger">
        <TriangleAlert className="h-6 w-6" aria-hidden="true" />
      </span>
      <div className="flex flex-col gap-1">
        <h1 className="font-serif text-h2 font-semibold text-foreground">
          Something went wrong
        </h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          An unexpected error occurred. You can try again, or head back to the dashboard.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Button size="sm" onClick={reset}>
          Try Again
        </Button>
        <Button size="sm" variant="outline" href="/dashboard">
          Go to Dashboard
        </Button>
      </div>
    </div>
  );
}
