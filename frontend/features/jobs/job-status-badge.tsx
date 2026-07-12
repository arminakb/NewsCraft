import { Badge } from "@/components/ui/badge"
import type { JobStatus } from "@/features/jobs/types"
import { cn } from "@/lib/utils"

const styles: Record<JobStatus, string> = {
  queued: "border-slate-200 bg-slate-50 text-slate-700",
  running: "border-blue-200 bg-blue-50 text-blue-700",
  succeeded: "border-emerald-200 bg-emerald-50 text-emerald-700",
  failed: "border-red-200 bg-red-50 text-red-700",
  needs_review: "border-amber-200 bg-amber-50 text-amber-800",
  cancelled: "border-slate-200 bg-slate-100 text-slate-600",
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <Badge variant="outline" className={cn("capitalize", styles[status])}>
      {status.replace("_", " ")}
    </Badge>
  )
}
