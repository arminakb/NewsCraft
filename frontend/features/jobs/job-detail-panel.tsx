"use client"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingState } from "@/components/ui/state-panel"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import type { WorkflowJobDetail } from "@/features/jobs/types"
import { getApiErrorMessage } from "@/lib/http"
import { formatInTimeZone } from "@/lib/date-time"

export function JobDetailPanel({
  job,
  isLoading,
  error,
  mutationPending,
  onClose,
  onRetry,
  onCancel,
}: {
  job?: WorkflowJobDetail
  isLoading: boolean
  error: unknown
  mutationPending: boolean
  onClose: () => void
  onRetry: () => void
  onCancel: () => void
}) {
  const { timezone } = useDateTime()
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className="my-0 h-[calc(100dvh-1rem)] max-h-[calc(100dvh-1rem)] max-w-2xl justify-self-end overflow-y-auto p-4 sm:h-[calc(100dvh-2rem)] sm:max-h-[calc(100dvh-2rem)] sm:p-5"
        viewportClassName="place-items-stretch p-2 sm:p-4 sm:pl-[min(20vw,16rem)]"
      >
        <DialogHeader className="flex-row items-start justify-between gap-3">
          <div>
            <DialogTitle>Job details</DialogTitle>
            <DialogDescription>Durable execution state, evidence, and available operator actions.</DialogDescription>
          </div>
          <DialogClose autoFocus aria-label="Close job details" className={buttonVariants({ variant: "outline" })}>
            Close
          </DialogClose>
        </DialogHeader>

        {isLoading ? <LoadingState className="mt-6" title="Loading job details…" /> : null}
        {error ? (
          <Alert className="mt-6" tone="error" role="alert" dir="auto">
            <div>
              <AlertTitle>Job details unavailable</AlertTitle>
              <AlertDescription>{getApiErrorMessage(error, "Job detail request failed")}</AlertDescription>
            </div>
          </Alert>
        ) : null}
        {job ? (
          <div className="mt-6 space-y-6">
            <section aria-label="Job status" className="space-y-4 rounded-md border border-border/60 p-3 sm:p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <span className="block font-medium">{humanize(job.job_type)}</span>
                  <span className="text-xs text-muted-foreground">{job.origin} job</span>
                </div>
                <JobStatusBadge status={job.status} />
              </div>
              <dl className="grid grid-cols-[minmax(7rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                <DetailTerm>Created</DetailTerm><DetailValue>{formatTime(job.created_at, timezone)}</DetailValue>
                <DetailTerm>Scheduled</DetailTerm><DetailValue>{formatTime(job.scheduled_for, timezone)}</DetailValue>
                <DetailTerm>Started</DetailTerm><DetailValue>{formatTime(job.started_at, timezone)}</DetailValue>
                <DetailTerm>Finished</DetailTerm><DetailValue>{formatTime(job.finished_at, timezone)}</DetailValue>
                <DetailTerm>Duration</DetailTerm><DetailValue>{formatDuration(job.started_at, job.finished_at)}</DetailValue>
                <DetailTerm>Attempts</DetailTerm><DetailValue>{job.attempt_count} of {job.max_attempts}</DetailValue>
                <DetailTerm>Progress</DetailTerm><DetailValue dir="auto">{job.progress}% {job.progress_message ?? ""}</DetailValue>
              </dl>
              {job.error_code || job.error_message ? (
                <div className="rounded-md bg-[var(--error-surface)] p-3 text-sm" role="status">
                  <div className="font-medium text-destructive">Failure details</div>
                  {job.error_code ? <code className="mt-1 block break-all text-xs text-destructive">{job.error_code}</code> : null}
                  {job.error_message ? <p className="mt-1 break-words text-foreground" dir="auto">{job.error_message}</p> : null}
                  <p className="mt-2 text-xs text-muted-foreground">{recoveryText(job.error_class)}</p>
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {job.status === "failed" || job.status === "needs_review" ? (
                  <Button disabled={mutationPending} onClick={onRetry}>{mutationPending ? "Retrying…" : "Retry job"}</Button>
                ) : null}
                {job.status === "queued" ? (
                  <Button variant="destructive" disabled={mutationPending} onClick={onCancel}>{mutationPending ? "Cancelling…" : "Cancel job"}</Button>
                ) : null}
                <Button
                  variant="outline"
                  onClick={() => void navigator.clipboard?.writeText(job.id)}
                >
                  Copy job ID
                </Button>
              </div>
            </section>
            <section aria-labelledby="job-timeline-heading" className="space-y-3">
              <div>
                <h3 className="font-semibold" id="job-timeline-heading">Lifecycle timeline</h3>
                <p className="text-xs text-muted-foreground">Recorded events only. Payloads and worker internals stay hidden.</p>
              </div>
              {job.events.length ? (
                <ol className="relative space-y-0 border-l border-border/70 pl-4">
                  {[...job.events].reverse().map((event) => (
                    <li className="relative pb-4 last:pb-0" key={event.id}>
                      <span aria-hidden="true" className="absolute -left-[1.19rem] top-1.5 size-2 rounded-full bg-muted-foreground ring-4 ring-background" />
                      <div className="font-medium">{humanize(event.event_type)}</div>
                      <time className="text-xs text-muted-foreground" dateTime={event.created_at}>{formatInTimeZone(event.created_at, timezone)}</time>
                    </li>
                  ))}
                </ol>
              ) : <div className="text-sm text-muted-foreground">No lifecycle events recorded.</div>}
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function DetailTerm({ children }: { children: React.ReactNode }) {
  return <dt className="text-muted-foreground">{children}</dt>
}

function DetailValue({ children, dir }: { children: React.ReactNode; dir?: "auto" }) {
  return <dd className="min-w-0 break-words" dir={dir}>{children}</dd>
}

function formatTime(value: string | null, timezone: string) {
  return value ? formatInTimeZone(value, timezone) : "Not recorded"
}

function formatDuration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt) return "Not started"
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "Unknown"
  const seconds = Math.floor((end - start) / 1_000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function recoveryText(errorClass: WorkflowJobDetail["error_class"]) {
  if (errorClass === "retryable") return "Retry after confirming the affected dependency is available."
  if (errorClass === "needs_review") return "Review related content or destination state before retrying."
  return "Inspect the safe error code and related operational checks before taking action."
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replaceAll(".", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
