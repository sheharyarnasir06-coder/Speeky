import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

// First reusable pagination control in the app — Users list (Super Admin) is
// the first paginated endpoint this project has, so there's no prior pattern
// to match beyond the existing button/border styling conventions.
export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;

  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="flex items-center justify-between gap-4 text-sm text-muted-foreground">
      <span>
        Showing {from}-{to} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-surface disabled:pointer-events-none disabled:opacity-40",
          )}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </button>
        <span className="px-2 text-foreground">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-surface disabled:pointer-events-none disabled:opacity-40",
          )}
        >
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
