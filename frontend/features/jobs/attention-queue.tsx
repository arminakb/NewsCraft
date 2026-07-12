import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import type { WorkflowJob } from "@/features/jobs/types"

export function AttentionQueue({
  jobs,
  pendingJobId,
  onRetry,
  onCancel,
}: {
  jobs: WorkflowJob[]
  pendingJobId?: string | null
  onRetry: (id: string) => void
  onCancel: (id: string) => void
}) {
  return (
    <Card size="sm" role="region" aria-label="Attention queue">
      <CardHeader className="border-b"><CardTitle>Needs attention</CardTitle></CardHeader>
      <CardContent className="divide-y px-0">
        {jobs.length ? jobs.map((job) => (
          <div key={job.id} className="flex flex-wrap items-center gap-3 px-3 py-3">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{job.jobType}</div>
              <div dir="auto" className="text-sm text-red-700">{job.errorMessage ?? job.errorCode ?? "Action required"}</div>
            </div>
            <JobStatusBadge status={job.status} />
            {job.status === "failed" || job.status === "needs_review" ? (
              <Button variant="outline" disabled={pendingJobId === job.id} onClick={() => onRetry(job.id)}>Retry</Button>
            ) : null}
            {job.status === "queued" ? (
              <Button variant="outline" disabled={pendingJobId === job.id} onClick={() => onCancel(job.id)}>Cancel</Button>
            ) : null}
          </div>
        )) : <div className="px-3 py-6 text-center text-muted-foreground">No jobs need attention</div>}
      </CardContent>
    </Card>
  )
}
