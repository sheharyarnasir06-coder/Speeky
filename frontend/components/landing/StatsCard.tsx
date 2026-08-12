import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StatCard as StatCardData } from "@/lib/types";

interface StatsCardProps {
  stat: StatCardData;
}

export function StatsCard({ stat }: StatsCardProps) {
  const { icon: Icon, label, value, delta, trend } = stat;

  return (
    <div className="group flex min-h-[8.5rem] flex-col gap-4 rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-center justify-between">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-secondary text-primary transition-colors group-hover:bg-primary group-hover:text-white">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        {delta ? (
          <span
            className={cn(
              "flex items-center gap-1 text-xs font-medium",
              trend === "up" && "text-success",
              trend === "down" && "text-danger",
              trend === "neutral" && "text-muted-foreground",
            )}
          >
            {trend === "up" ? (
              <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
            ) : null}
            {delta}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-h2 font-semibold tracking-tight text-foreground">
          {value}
        </span>
        <span className="text-sm text-muted-foreground">{label}</span>
      </div>
    </div>
  );
}
