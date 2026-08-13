"use client"

import { Eye } from "lucide-react"

import { useDateTime } from "@/components/providers/date-time-provider"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import type { WorkflowJob } from "@/features/jobs/types"
import { formatInTimeZone } from "@/lib/date-time"

export function JobTable({
  jobs,
  selectedId,
  onSelect,
}: {
  jobs: WorkflowJob[]
  selectedId?: string | null
  onSelect: (job: WorkflowJob, trigger: HTMLButtonElement) => void
}) {
  const { timezone } = useDateTime()
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Job type</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="hidden lg:table-cell">Duration</TableHead>
              <TableHead>Attempts</TableHead>
              <TableHead className="hidden xl:table-cell">Last safe error</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow key={job.id} data-state={selectedId === job.id ? "selected" : undefined}>
                <TableCell><JobStatusBadge status={job.status} /></TableCell>
                <TableCell className="max-w-64">
                  <div className="font-medium">{humanize(job.job_type)}</div>
                  {job.progress_message ? <div dir="auto" className="max-w-64 truncate text-xs text-muted-foreground" title={job.progress_message}>{job.progress_message}</div> : null}
                </TableCell>
                <TableCell><time className="tabular-nums" dateTime={job.created_at}>{formatTimestamp(job.created_at, timezone)}</time></TableCell>
                <TableCell className="hidden tabular-nums lg:table-cell">{formatDuration(job.started_at, job.finished_at)}</TableCell>
                <TableCell className="tabular-nums">{job.attempt_count} / {job.max_attempts}</TableCell>
                <TableCell className="hidden max-w-72 xl:table-cell">
                  <div className="truncate" dir="auto" title={job.error_message ?? job.error_code ?? undefined}>
                    {job.error_message ?? job.error_code ?? "—"}
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    aria-label={`View ${humanize(job.job_type)} job details`}
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
      </div>
      <ul aria-label="Jobs" className="divide-y md:hidden">
        {jobs.map((job) => (
          <li className="space-y-3 p-3" key={job.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium">{humanize(job.job_type)}</div>
                <time className="text-xs text-muted-foreground" dateTime={job.created_at}>{formatTimestamp(job.created_at, timezone)}</time>
              </div>
              <JobStatusBadge status={job.status} />
            </div>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <div><dt className="text-muted-foreground">Attempts</dt><dd className="tabular-nums">{job.attempt_count} / {job.max_attempts}</dd></div>
              <div><dt className="text-muted-foreground">Duration</dt><dd>{formatDuration(job.started_at, job.finished_at)}</dd></div>
            </dl>
            {job.error_message || job.error_code ? <p className="break-words text-sm text-destructive" dir="auto">{job.error_message ?? job.error_code}</p> : null}
            <Button
              className="w-full"
              variant="outline"
              aria-label={`View ${humanize(job.job_type)} job details`}
              onClick={(event) => onSelect(job, event.currentTarget)}
            >
              <Eye aria-hidden="true" />
              View details
            </Button>
          </li>
        ))}
      </ul>
    </>
  )
}

function formatTimestamp(value: string, timezone: string) {
  return formatInTimeZone(value, timezone, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function formatDuration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt) return "Not started"
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "Unknown"
  const seconds = Math.floor((end - start) / 1_000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replaceAll(".", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
