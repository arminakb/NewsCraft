"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { getContentPackRequests } from "@/features/editorial/api"
import type { ContentPackRequestSummary } from "@/features/editorial/types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

type DraftFilter = "needs_review" | "ready" | "failed" | "all"

const filters: Array<{ id: DraftFilter; label: string }> = [
  { id: "needs_review", label: "Needs review" },
  { id: "ready", label: "Ready for handoff" },
  { id: "failed", label: "Failed" },
  { id: "all", label: "All" },
]

export default function DraftsPage() {
  const [filter, setFilter] = useState<DraftFilter>(initialFilter)
  const requests = useQuery({
    queryKey: queryKeys.contentPackRequests,
    queryFn: getContentPackRequests,
  })
  const counts = useMemo(
    () => Object.fromEntries(filters.map(({ id }) => [id, requests.data?.filter((request) => matchesFilter(request, id)).length ?? 0])),
    [requests.data],
  )
  const visible = requests.data?.filter((request) => matchesFilter(request, filter)) ?? []

  return (
    <section className="space-y-6 p-4 md:p-6" aria-labelledby="drafts-heading">
      <header className="space-y-1">
        <h1 id="drafts-heading" className="text-2xl font-semibold">Drafts</h1>
        <p className="text-muted-foreground">Review generated packages, resolve failures, and hand off approved work.</p>
      </header>

      <nav aria-label="Draft views" className="flex flex-wrap gap-2">
        {filters.map((item) => (
          <Button
            key={item.id}
            type="button"
            variant={filter === item.id ? "default" : "outline"}
            aria-pressed={filter === item.id}
            onClick={() => setFilter(item.id)}
          >
            {item.label} <span aria-hidden="true">({counts[item.id]})</span>
          </Button>
        ))}
      </nav>

      <section aria-live="polite" aria-busy={requests.isPending}>
        {requests.isPending ? (
          <div role="status" className="grid gap-3">
            <span>Loading drafts…</span>
            <div className="h-28 animate-pulse rounded-lg border bg-muted/40" />
            <div className="h-28 animate-pulse rounded-lg border bg-muted/40" />
          </div>
        ) : null}

        {requests.isError ? (
          <div className="space-y-3 rounded-lg border border-red-300 p-4">
            <div role="alert" className="text-red-700">
              {getApiErrorMessage(requests.error, "Drafts could not be loaded")}
            </div>
            <Button type="button" variant="outline" onClick={() => void requests.refetch()}>Retry drafts</Button>
          </div>
        ) : null}

        {requests.isSuccess && visible.length ? (
          <ul className="grid gap-3">
            {visible.map((request) => <DraftCard key={request.id} request={request} />)}
          </ul>
        ) : null}

        {requests.isSuccess && !visible.length ? (
          <div className="rounded-lg border border-dashed p-6">
            <h2 className="font-semibold">{emptyTitle(filter)}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{emptyMessage(filter)}</p>
          </div>
        ) : null}
      </section>
    </section>
  )
}

function DraftCard({ request }: { request: ContentPackRequestSummary }) {
  const state = draftState(request)
  const title = request.pack ? "Content package" : "Generation request"
  const action = request.pack
    ? state === "ready"
      ? { label: "Open handoff", href: `/drafts/${request.pack.id}` }
      : { label: "Continue review", href: `/drafts/${request.pack.id}` }
    : null

  return (
    <li className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">{title}</h2>
          <p className="text-sm text-muted-foreground">
            {stateLabel(state)} · updated {new Date(request.updatedAt).toLocaleString()}
          </p>
        </div>
        {action ? <Link href={action.href} className="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground">{action.label}</Link> : null}
      </div>

      {!request.pack ? (
        <div role="status" className="text-sm">
          {state === "failed" || state === "needs_review"
            ? "Review required before a pack can be created."
            : "Generation has not created a pack yet."}
        </div>
      ) : null}

      <details className="rounded-md border p-3" open={Boolean(request.lastFailure)}>
        <summary className="cursor-pointer font-medium">Advanced details{request.lastFailure ? " — blocker" : ""}</summary>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <div><dt className="text-muted-foreground">Story</dt><dd className="break-all">{request.storyId}</dd></div>
          <div><dt className="text-muted-foreground">Durable job</dt><dd className="break-all">{request.jobId ?? "Not attached"}</dd></div>
          <div><dt className="text-muted-foreground">Created</dt><dd>{new Date(request.createdAt).toLocaleString()}</dd></div>
          <div><dt className="text-muted-foreground">Backend status</dt><dd>{request.status.replaceAll("_", " ")}</dd></div>
        </dl>
        {request.lastFailure ? <div role="alert" className="mt-3 text-sm text-red-700">Last failure: {request.lastFailure}</div> : null}
      </details>
    </li>
  )
}

function initialFilter(): DraftFilter {
  if (typeof window === "undefined") return "needs_review"
  const params = new URLSearchParams(window.location.search)
  if (params.get("status") === "failed") return "failed"
  if (params.get("approval_state") === "pending_review") return "needs_review"
  return "needs_review"
}

function draftState(request: ContentPackRequestSummary): Exclude<DraftFilter, "all"> | "in_progress" {
  if (request.status === "failed") return "failed"
  if (request.pack?.status === "ready" || request.status === "ready") return "ready"
  if (request.status === "needs_review" || (request.pack && request.pack.status !== "ready")) return "needs_review"
  return "in_progress"
}

function matchesFilter(request: ContentPackRequestSummary, filter: DraftFilter) {
  return filter === "all" || draftState(request) === filter
}

function stateLabel(state: ReturnType<typeof draftState>) {
  if (state === "needs_review") return "Needs review"
  if (state === "ready") return "Ready for handoff"
  if (state === "failed") return "Failed"
  return "Generation in progress"
}

function emptyTitle(filter: DraftFilter) {
  if (filter === "needs_review") return "Nothing needs review"
  if (filter === "ready") return "Nothing is ready for handoff"
  if (filter === "failed") return "No failed drafts"
  return "No durable generation requests yet."
}

function emptyMessage(filter: DraftFilter) {
  if (filter === "needs_review") return "Generated packages requiring an editorial decision will appear here."
  if (filter === "ready") return "Approved packages will appear here when they are ready to publish or export."
  if (filter === "failed") return "Generation failures that need recovery will appear here."
  return "Create a content package from Inbox to begin."
}
