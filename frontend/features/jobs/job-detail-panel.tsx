"use client"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="my-0 h-[calc(100dvh-2rem)] max-h-[calc(100dvh-2rem)] max-w-xl justify-self-end overflow-y-auto p-4">
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
            <section aria-label="Job status" className="space-y-3 rounded-md border p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{job.job_type}</span>
                <JobStatusBadge status={job.status} />
              </div>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Origin</dt><dd>{job.origin}</dd>
                <dt className="text-muted-foreground">Attempts</dt><dd>{job.attempt_count} / {job.max_attempts}</dd>
                <dt className="text-muted-foreground">Progress</dt><dd dir="auto">{job.progress}% {job.progress_message ?? ""}</dd>
                <dt className="text-muted-foreground">Error</dt><dd dir="auto">{job.error_message ?? "-"}</dd>
              </dl>
              <div className="flex gap-2">
                {job.status === "failed" || job.status === "needs_review" ? (
                  <Button disabled={mutationPending} onClick={onRetry}>Retry job</Button>
                ) : null}
                {job.status === "queued" ? (
                  <Button variant="destructive" disabled={mutationPending} onClick={onCancel}>Cancel job</Button>
                ) : null}
              </div>
            </section>
            <details className="space-y-3 rounded-md border p-3">
              <summary className="cursor-pointer font-semibold">Advanced execution evidence</summary>
              <p className="break-all text-xs text-muted-foreground">Job record {job.id}</p>
              <JsonSection title="Payload" value={job.payload} />
              <JsonSection title="Result" value={job.result} />
              <section aria-label="Job events" className="space-y-2">
                <h3 className="font-semibold">Events</h3>
                {job.events.length ? job.events.map((event) => (
                  <article key={event.id} className="rounded-md border p-3">
                    <div className="flex flex-wrap justify-between gap-2">
                      <span className="font-medium">{event.event_type}</span>
                      <time className="text-xs text-muted-foreground" dateTime={event.created_at}>{event.created_at}</time>
                    </div>
                    <div className="text-xs text-muted-foreground">{event.actor}</div>
                    <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs" dir="auto">{safeJson(event.event_data)}</pre>
                  </article>
                )) : <div className="text-sm text-muted-foreground">No events recorded</div>}
              </section>
            </details>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function JsonSection({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <section aria-label={`Job ${title.toLowerCase()}`} className="space-y-2">
      <h3 className="font-semibold">{title}</h3>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border bg-muted p-3 text-xs" dir="auto">{safeJson(value)}</pre>
    </section>
  )
}

function safeJson(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2)
}
