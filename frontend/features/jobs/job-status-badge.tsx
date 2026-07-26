import { Badge } from "@/components/ui/badge"
import type { JobStatus } from "@/features/jobs/types"

const variants: Record<JobStatus, "default" | "error" | "neutral" | "success" | "warning"> = {
  queued: "neutral",
  running: "default",
  succeeded: "success",
  failed: "error",
  needs_review: "warning",
  cancelled: "neutral",
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <Badge variant={variants[status]} className="capitalize">
      {status.replace("_", " ")}
    </Badge>
  )
}
