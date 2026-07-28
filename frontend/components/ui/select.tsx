import * as React from "react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "className"> {
  label?: string;
  hideLabel?: boolean;
  hint?: string;
  options: SelectOption[];
}

// Wraps the raw <select> styling every page was already hand-rolling
// (admin/scenarios/page.tsx's category/goal-type selects) into one component.
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, hideLabel, hint, options, id, ...props }, ref) => {
    const generatedId = React.useId();
    const selectId = id ?? generatedId;
    return (
      <div className="flex flex-col gap-1.5">
        {label ? (
          <label
            htmlFor={selectId}
            className={cn("text-sm font-medium text-foreground", hideLabel && "sr-only")}
          >
            {label}
          </label>
        ) : null}
        <select
          id={selectId}
          ref={ref}
          className="h-11 w-full rounded-xl border border-input bg-surface px-4 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          {...props}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </div>
    );
  },
);

Select.displayName = "Select";
