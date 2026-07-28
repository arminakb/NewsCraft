import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import type { JobStatus } from "@/features/jobs/types"

const tones: Record<JobStatus, StatusTone> = {
  queued: "neutral",
  running: "info",
  succeeded: "success",
  failed: "error",
  needs_review: "warning",
  cancelled: "neutral",
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <StatusBadge tone={tones[status]} className="capitalize">
      {status.replace("_", " ")}
    </StatusBadge>
  )
}
