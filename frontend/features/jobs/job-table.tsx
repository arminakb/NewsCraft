import { Eye } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import type { WorkflowJob } from "@/features/jobs/types"

export function JobTable({
  jobs,
  selectedId,
  onSelect,
}: {
  jobs: WorkflowJob[]
  selectedId?: string | null
  onSelect: (job: WorkflowJob, trigger: HTMLButtonElement) => void
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Job</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Origin</TableHead>
          <TableHead>Progress</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead className="text-right">Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.id} data-state={selectedId === job.id ? "selected" : undefined}>
            <TableCell>
              <div className="font-medium">{job.jobType}</div>
              <div className="text-xs text-muted-foreground">{job.id}</div>
            </TableCell>
            <TableCell><JobStatusBadge status={job.status} /></TableCell>
            <TableCell className="capitalize">{job.origin}</TableCell>
            <TableCell>
              <span dir="auto">{job.progress}%</span>
              {job.progressMessage ? <div dir="auto" className="max-w-56 truncate text-xs text-muted-foreground">{job.progressMessage}</div> : null}
            </TableCell>
            <TableCell><time dateTime={job.updatedAt}>{formatTimestamp(job.updatedAt)}</time></TableCell>
            <TableCell className="text-right">
              <Button
                variant="ghost"
                aria-label={`View ${job.jobType} job ${job.id}`}
                onClick={(event) => onSelect(job, event.currentTarget)}
              >
                <Eye aria-hidden="true" />
                View
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function formatTimestamp(value: string) {
  return value.replace("T", " ").replace(/\.\d+Z$/, "Z")
}
