import { Circle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { SourceStatus } from "@/lib/types"

const statusStyles: Record<SourceStatus, string> = {
  healthy: "border-emerald-200 bg-emerald-50 text-emerald-700",
  partial: "border-amber-200 bg-amber-50 text-amber-700",
  failed: "border-red-200 bg-red-50 text-red-700",
}

const dotStyles: Record<SourceStatus, string> = {
  healthy: "fill-emerald-600 text-emerald-600",
  partial: "fill-amber-500 text-amber-500",
  failed: "fill-red-600 text-red-600",
}

export function StatusBadge({ status, className }: { status: SourceStatus; className?: string }) {
  const label = status === "partial" ? "Partial" : status === "failed" ? "Failed" : "Healthy"

  return (
    <Badge variant="outline" className={cn("h-6 gap-1.5 rounded-md px-2", statusStyles[status], className)}>
      <Circle className={cn("size-2", dotStyles[status])} aria-hidden="true" />
      {label}
    </Badge>
  )
}
