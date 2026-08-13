"use client"

import { useInfiniteQuery } from "@tanstack/react-query"
import { ArrowUpRight } from "lucide-react"
import Link from "next/link"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { getApiErrorMessage } from "@/lib/http"
import { operationsQueryKeys } from "@/lib/query-keys"

import { fetchOperationsHistory } from "./api"
import { formatOperatorTimestamp } from "./diagnostics-dashboard"
import type { HistoryEntry, HistoryFilters } from "./types"

export function HistoryTimeline({ routeId }: { routeId: string }) {
  const { timezone } = useDateTime()
  const filters: HistoryFilters = {
    subjectType: "automation_route",
    subjectId: routeId,
    limit: 50,
  }
  const historyQuery = useInfiniteQuery({
    queryKey: operationsQueryKeys.history(filters),
    queryFn: ({ pageParam }) =>
      fetchOperationsHistory({
        ...filters,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  })
  const entries = historyQuery.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <Card className="rounded-md py-0" size="sm">
      <CardHeader className="border-b px-3 py-3">
        <CardTitle className="text-base">Durable route history</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {historyQuery.isPending ? (
          <LoadingState aria-label="Loading route history" className="m-3" title="Loading route history…" />
        ) : null}
        {historyQuery.isError ? (
          <ErrorState
            className="m-3"
            dir="auto"
            title="Route history unavailable"
            description={getApiErrorMessage(historyQuery.error, "Route history could not be loaded")}
            action={<Button onClick={() => historyQuery.refetch()} size="sm" variant="outline">Retry history</Button>}
          />
        ) : null}
        {historyQuery.isSuccess && entries.length === 0 ? (
          <EmptyState className="m-3" title="No durable route history" description="No durable history has been recorded for this route." />
        ) : null}
        {entries.length ? (
          <ol className="divide-y">
            {entries.map((entry) => (
              <HistoryTimelineItem entry={entry} key={entry.id} timezone={timezone} />
            ))}
          </ol>
        ) : null}
        {historyQuery.hasNextPage ? (
          <div className="border-t p-3 text-center">
            <Button
              disabled={historyQuery.isFetchingNextPage}
              onClick={() => historyQuery.fetchNextPage()}
              variant="outline"
            >
              {historyQuery.isFetchingNextPage ? "Loading more history…" : "Load more history"}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function HistoryTimelineItem({ entry, timezone }: { entry: HistoryEntry; timezone: string }) {
  const metadata = Object.entries(entry.sanitized_metadata)

  return (
    <li className="relative grid gap-3 px-4 py-4 md:grid-cols-[150px_minmax(0,1fr)_auto]">
      <div className="space-y-1">
        <time className="text-sm font-medium tabular-nums" dateTime={entry.occurred_at}>
          {formatOperatorTimestamp(entry.occurred_at, timezone)}
        </time>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline">{humanize(entry.category)}</Badge>
          <Badge variant="secondary">{humanize(entry.status)}</Badge>
        </div>
      </div>

      <div className="min-w-0 space-y-2">
        <DirectionBoundary as="h3" className="font-medium" direction="auto">
          {entry.title}
        </DirectionBoundary>
        <DirectionBoundary className="text-sm text-muted-foreground" direction="auto">
          {entry.summary}
        </DirectionBoundary>
        {entry.job_id ? <p className="text-xs text-muted-foreground">Workflow job {entry.job_id}</p> : null}
        {metadata.length ? (
          <dl className="grid gap-2 rounded-md border border-border/50 bg-muted/35 p-3 text-xs sm:grid-cols-2">
            {metadata.map(([key, value]) => (
              <div className="min-w-0" key={key}>
                <dt className="font-medium text-muted-foreground">{key}</dt>
                <dd>
                  <DirectionBoundary
                    as="pre"
                    className="mt-1 whitespace-pre-wrap break-all font-mono text-xs"
                    direction="auto"
                  >
                    {formatMetadata(value)}
                  </DirectionBoundary>
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>

      <Link
        className="inline-flex items-center gap-1 self-start text-sm font-medium text-primary underline-offset-4 hover:underline"
        href={entry.subject_url}
      >
        Open related record
        <ArrowUpRight aria-hidden="true" className="size-3.5" />
      </Link>
    </li>
  )
}

function formatMetadata(value: unknown): string {
  if (value === undefined) return "undefined"
  return JSON.stringify(value, null, 2)
}

function humanize(value: string): string {
  return value.replaceAll("_", " ")
}
