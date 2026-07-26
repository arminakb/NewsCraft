import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import type { WorkflowJob } from "@/features/jobs/types"
import Link from "next/link"

export function AttentionQueue({
  jobs,
}: {
  jobs: WorkflowJob[]
}) {
  return (
    <Card size="sm" role="region" aria-label="Attention queue">
      <CardHeader className="border-b"><CardTitle>Needs attention</CardTitle></CardHeader>
      <CardContent className="divide-y px-0">
        {jobs.length ? jobs.map((job) => (
          <div key={job.id} className="flex flex-wrap items-center gap-3 px-3 py-3">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{job.job_type}</div>
              <div dir="auto" className="text-sm text-red-700">{job.error_message ?? job.error_code ?? "Action required"}</div>
            </div>
            <JobStatusBadge status={job.status} />
            {job.status === "failed" ? (
              <Link className={buttonVariants({ variant: "outline" })} href={`/jobs?status=attention&job=${job.id}`}>
                Open job
              </Link>
            ) : job.status === "needs_review" ? (
              <Link className={buttonVariants({ variant: "outline" })} href={`/jobs?status=attention&job=${job.id}`}>
                Continue review
              </Link>
            ) : null}
          </div>
        )) : <div className="px-3 py-6 text-center text-muted-foreground">No jobs need attention</div>}
      </CardContent>
    </Card>
  )
}
