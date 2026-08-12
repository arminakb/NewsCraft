"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, History, LoaderCircle } from "lucide-react"
import { useState } from "react"

import { useDateTime } from "@/components/providers/date-time-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import {
  getSourceCollectionRuns,
  type SourceCollectionRun,
} from "@/features/operations/ingestion-api"
import { formatInTimeZone } from "@/lib/date-time"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

const HISTORY_PAGE_SIZE = 25
const ACTIVE_RUN_STATUSES = new Set(["queued", "running"])

type CollectionRunHistoryProps = {
  collectionId: string
  collectionName: string
  hasMore: boolean
  runs: SourceCollectionRun[]
}

export function CollectionRunHistory({
  collectionId,
  collectionName,
  hasMore,
  runs,
}: CollectionRunHistoryProps) {
  const [historyOpen, setHistoryOpen] = useState(false)

  return (
    <section
      aria-labelledby="recent-ingestion-history-heading"
      className="mt-4 rounded-md border border-border/70 bg-card px-3 py-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-medium" id="recent-ingestion-history-heading">
          Recent ingestion history
        </h4>
        {runs.length ? (
          <span className="text-xs text-muted-foreground">Latest {runs.length}</span>
        ) : null}
      </div>

      {runs.length ? (
        <ol aria-label="Recent ingestion runs" className="mt-2 divide-y divide-border/60">
          {runs.map((run) => <CollectionRunHistoryItem key={run.id} run={run} />)}
        </ol>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">No ingestion runs yet.</p>
      )}

      {hasMore ? (
        <div className="mt-1 border-t border-border/60 pt-1 text-center">
          <Button
            className="min-h-11 cursor-pointer gap-1.5"
            onClick={() => setHistoryOpen(true)}
            type="button"
            variant="ghost"
          >
            <History aria-hidden="true" className="size-4" />
            View history
          </Button>
        </div>
      ) : null}

      {historyOpen ? (
        <CollectionRunHistoryDialog
          collectionId={collectionId}
          collectionName={collectionName}
          onClose={() => setHistoryOpen(false)}
        />
      ) : null}
    </section>
  )
}

function CollectionRunHistoryDialog({
  collectionId,
  collectionName,
  onClose,
}: {
  collectionId: string
  collectionName: string
  onClose: () => void
}) {
  const [offset, setOffset] = useState(0)
  const historyQuery = useQuery({
    queryKey: queryKeys.sourceCollectionRunHistory(collectionId, HISTORY_PAGE_SIZE, offset),
    queryFn: ({ signal }) => getSourceCollectionRuns(
      collectionId,
      { limit: HISTORY_PAGE_SIZE, offset },
      signal,
    ),
    placeholderData: keepPreviousData,
  })
  const runs = historyQuery.data?.items ?? []
  const total = historyQuery.data?.total ?? 0
  const visibleOffset = historyQuery.data?.offset ?? offset

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[min(44rem,calc(100dvh-2rem))] max-w-2xl flex-col p-0">
        <DialogHeader className="border-b border-border/60 px-5 py-4">
          <DialogTitle>Ingestion history · {collectionName}</DialogTitle>
          <DialogDescription>
            Runs load {HISTORY_PAGE_SIZE} at a time. Summary counts come from persisted ingestion results.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-32 overflow-y-auto px-5">
          {historyQuery.isPending ? (
            <LoadingState className="my-4" title="Loading ingestion history…" />
          ) : null}
          {historyQuery.isError ? (
            <ErrorState
              action={(
                <Button onClick={() => historyQuery.refetch()} size="sm" variant="outline">
                  Retry history
                </Button>
              )}
              className="my-4"
              description={getApiErrorMessage(historyQuery.error, "Ingestion history could not be loaded.")}
              title="History unavailable"
            />
          ) : null}
          {historyQuery.isSuccess && runs.length === 0 ? (
            <EmptyState
              className="my-4"
              description="No ingestion runs have been recorded for this Source Collection."
              title="No ingestion history"
            />
          ) : null}
          {runs.length ? (
            <ol aria-label="Ingestion run history" className="divide-y divide-border/60">
              {runs.map((run) => <CollectionRunHistoryItem key={run.id} run={run} />)}
            </ol>
          ) : null}
        </div>

        <DialogFooter className="shrink-0 justify-between px-5 py-4">
          <div className="flex items-center gap-2 text-xs tabular-nums text-muted-foreground" aria-live="polite">
            {historyQuery.isFetching && !historyQuery.isPending ? (
              <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin motion-reduce:animate-none" />
            ) : null}
            <span>
              {runs.length ? `${visibleOffset + 1}–${visibleOffset + runs.length} of ${total} runs` : ""}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-h-11"
              disabled={offset === 0 || historyQuery.isFetching}
              onClick={() => setOffset((current) => Math.max(0, current - HISTORY_PAGE_SIZE))}
              type="button"
              variant="outline"
            >
              <ChevronLeft aria-hidden="true" className="size-4" />
              Previous
            </Button>
            <Button
              className="min-h-11"
              disabled={!historyQuery.data?.hasMore || historyQuery.isFetching}
              onClick={() => setOffset((current) => current + HISTORY_PAGE_SIZE)}
              type="button"
              variant="outline"
            >
              Next
              <ChevronRight aria-hidden="true" className="size-4" />
            </Button>
            <DialogClose render={<Button className="min-h-11" type="button">Close</Button>} />
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function CollectionRunHistoryItem({ run }: { run: SourceCollectionRun }) {
  const { timezone } = useDateTime()
  const active = ACTIVE_RUN_STATUSES.has(run.status)
  const remaining = Math.max(0, run.sourceCount - run.processedCount)
  const timestamp = active ? run.startedAt : run.completedAt ?? run.startedAt
  const timePrefix = active ? "Started" : run.completedAt ? "Completed" : "Started"

  return (
    <li className="grid gap-2 py-3 text-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-x-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="truncate text-sm font-medium">
            {run.sourceCollectionNameAtStart || "Source Collection"}
          </span>
          <Badge variant={runStatusVariant(run.status)}>{formatRunStatus(run.status)}</Badge>
        </div>
        <p className="mt-0.5 text-muted-foreground">
          {run.mode === "continuous"
            ? `Continuous · Cycle #${run.continuousCycleNumber ?? "–"}`
            : "Run once"}
        </p>
      </div>

      <div className="sm:text-right">
        <p className="tabular-nums text-muted-foreground">
          {run.sourceCount} {run.sourceCount === 1 ? "source" : "sources"}
        </p>
        <p className="mt-0.5 flex flex-wrap gap-x-1 tabular-nums sm:justify-end">
          <span className={run.successCount ? "text-success" : "text-muted-foreground"}>
            {run.successCount} succeeded
          </span>
          <span aria-hidden="true" className="text-muted-foreground">·</span>
          <span className={run.failureCount ? "text-destructive" : "text-muted-foreground"}>
            {run.failureCount} failed
          </span>
          {run.skippedCount ? (
            <>
              <span aria-hidden="true" className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">{run.skippedCount} skipped</span>
            </>
          ) : null}
          {active ? (
            <>
              <span aria-hidden="true" className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">{remaining} remaining</span>
            </>
          ) : null}
        </p>
        <time
          className="mt-0.5 block text-muted-foreground"
          dateTime={timestamp}
          suppressHydrationWarning
          title={formatInTimeZone(timestamp, timezone)}
        >
          {timePrefix} {formatRelativeRunTime(timestamp)}
        </time>
      </div>
    </li>
  )
}

function runStatusVariant(status: string): "error" | "neutral" | "success" | "warning" {
  if (status === "succeeded") return "success"
  if (["failed", "error"].includes(status)) return "error"
  if (["partial", "queued", "running"].includes(status)) return "warning"
  return "neutral"
}

function formatRunStatus(status: string): string {
  return status
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase())
}

export function formatRelativeRunTime(value: string, now = Date.now()): string {
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp)) return "at an unknown time"
  const elapsed = now - timestamp
  const future = elapsed < 0
  const seconds = Math.floor(Math.abs(elapsed) / 1_000)
  if (seconds < 45) return future ? "in moments" : "just now"
  const minutes = Math.max(1, Math.floor(seconds / 60))
  if (minutes < 60) return future ? `in ${minutes} min` : `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return future ? `in ${hours} hr` : `${hours} hr ago`
  const days = Math.floor(hours / 24)
  return future ? `in ${days} days` : `${days} days ago`
}
