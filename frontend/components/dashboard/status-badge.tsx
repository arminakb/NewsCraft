import { Circle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { SourceStatus } from "@/features/operations/ingestion-types"

const statusVariants: Record<SourceStatus, "error" | "neutral" | "success" | "warning"> = {
  healthy: "success",
  degraded: "warning",
  broken: "error",
  disabled: "neutral",
  unknown: "neutral",
}

const dotStyles: Record<SourceStatus, string> = {
  healthy: "fill-emerald-600 text-emerald-600",
  degraded: "fill-amber-500 text-amber-500",
  broken: "fill-red-600 text-red-600",
  disabled: "fill-slate-500 text-slate-500",
  unknown: "fill-zinc-500 text-zinc-500",
}

const statusLabels: Record<SourceStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  broken: "Broken",
  disabled: "Disabled",
  unknown: "Unknown",
}

export function StatusBadge({ status, className }: { status: SourceStatus; className?: string }) {
  return (
    <Badge variant={statusVariants[status]} className={cn("h-6 gap-1.5 rounded-md px-2", className)}>
      <Circle className={cn("size-2", dotStyles[status])} aria-hidden="true" />
      {statusLabels[status]}
    </Badge>
  )
}

export { statusLabels }
