"use client"

import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
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
  const panelRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== "Tab" || !panelRef.current) return
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => !(element instanceof HTMLButtonElement && element.disabled))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (!active || !panelRef.current.contains(active) || !focusable.includes(active as HTMLElement)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
        return
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [onClose])

  return (
    <aside
      ref={panelRef}
      role="dialog"
      aria-label="Job details"
      aria-modal="true"
      className="fixed inset-y-0 right-0 z-50 w-full max-w-xl overflow-y-auto border-l bg-white p-4 shadow-2xl"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Job details</h2>
          {job ? <div className="text-xs text-muted-foreground">{job.id}</div> : null}
        </div>
        <Button ref={closeRef} variant="outline" aria-label="Close job details" onClick={onClose}>Close</Button>
      </div>

      {isLoading ? <div role="status" className="mt-6">Loading job details</div> : null}
      {error ? <div role="alert" dir="auto" className="mt-6 text-red-700">{getApiErrorMessage(error, "Job detail request failed")}</div> : null}
      {job ? (
        <div className="mt-6 space-y-6">
          <section aria-label="Job status" className="space-y-3 rounded-md border p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{job.jobType}</span>
              <JobStatusBadge status={job.status} />
            </div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Origin</dt><dd>{job.origin}</dd>
              <dt className="text-muted-foreground">Attempts</dt><dd>{job.attemptCount} / {job.maxAttempts}</dd>
              <dt className="text-muted-foreground">Progress</dt><dd dir="auto">{job.progress}% {job.progressMessage ?? ""}</dd>
              <dt className="text-muted-foreground">Error</dt><dd dir="auto">{job.errorMessage ?? "-"}</dd>
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
          <JsonSection title="Payload" value={job.payload} />
          <JsonSection title="Result" value={job.result} />
          <section aria-label="Job events" className="space-y-2">
            <h3 className="font-semibold">Events</h3>
            {job.events.length ? job.events.map((event) => (
              <article key={event.id} className="rounded-md border p-3">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="font-medium">{event.eventType}</span>
                  <time className="text-xs text-muted-foreground" dateTime={event.createdAt}>{event.createdAt}</time>
                </div>
                <div className="text-xs text-muted-foreground">{event.actor}</div>
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs" dir="auto">{safeJson(event.eventData)}</pre>
              </article>
            )) : <div className="text-sm text-muted-foreground">No events recorded</div>}
          </section>
        </div>
      ) : null}
    </aside>
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
