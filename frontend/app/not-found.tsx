import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-secondary text-primary">
        <Compass className="h-6 w-6" aria-hidden="true" />
      </span>
      <div className="flex flex-col gap-1">
        <h1 className="font-serif text-h2 font-semibold text-foreground">Page not found</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          The page you&apos;re looking for doesn&apos;t exist or may have moved.
        </p>
      </div>
      <Button size="sm" href="/">
        Back to Home
      </Button>
    </div>
  );
}
