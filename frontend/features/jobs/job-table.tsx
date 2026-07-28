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
    <Table className="min-w-[680px]">
      <TableHeader>
        <TableRow>
          <TableHead>Job</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="hidden md:table-cell">Origin</TableHead>
          <TableHead>Progress</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead className="text-right">Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.id} data-state={selectedId === job.id ? "selected" : undefined}>
            <TableCell className="max-w-60">
              <div className="font-medium">{job.job_type}</div>
              <div className="truncate font-mono text-xs text-muted-foreground" title={job.id}>{job.id}</div>
            </TableCell>
            <TableCell><JobStatusBadge status={job.status} /></TableCell>
            <TableCell className="hidden capitalize md:table-cell">{job.origin}</TableCell>
            <TableCell>
              <span className="tabular-nums" dir="auto">{job.progress}%</span>
              {job.progress_message ? <div dir="auto" className="max-w-56 truncate text-xs text-muted-foreground" title={job.progress_message}>{job.progress_message}</div> : null}
            </TableCell>
            <TableCell><time className="tabular-nums" dateTime={job.updated_at}>{formatTimestamp(job.updated_at)}</time></TableCell>
            <TableCell className="text-right">
              <Button
                variant="ghost"
                aria-label={`View ${job.job_type} job ${job.id}`}
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
