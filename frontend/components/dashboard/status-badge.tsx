import { Circle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { SourceStatus } from "@/lib/types"

const statusStyles: Record<SourceStatus, string> = {
  healthy: "border-emerald-200 bg-emerald-50 text-emerald-700",
  degraded: "border-amber-200 bg-amber-50 text-amber-700",
  broken: "border-red-200 bg-red-50 text-red-700",
  disabled: "border-slate-200 bg-slate-50 text-slate-600",
  unknown: "border-zinc-200 bg-zinc-50 text-zinc-600",
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
    <Badge variant="outline" className={cn("h-6 gap-1.5 rounded-md px-2", statusStyles[status], className)}>
      <Circle className={cn("size-2", dotStyles[status])} aria-hidden="true" />
      {statusLabels[status]}
    </Badge>
  )
}

export { statusLabels }
