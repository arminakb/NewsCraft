import { StatusBadge as StatusBadgePrimitive, type StatusTone } from "@/components/ui/status-badge"
import type { SourceStatus } from "@/features/operations/ingestion-types"

const statusTones: Record<SourceStatus, StatusTone> = {
  healthy: "success",
  degraded: "warning",
  broken: "error",
  disabled: "neutral",
  unknown: "neutral",
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
    <StatusBadgePrimitive tone={statusTones[status]} className={className}>
      {statusLabels[status]}
    </StatusBadgePrimitive>
  )
}

export { statusLabels }
