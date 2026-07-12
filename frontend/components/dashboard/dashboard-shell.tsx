"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"

import { ContentQueuePanel } from "@/components/dashboard/content-queue-panel"
import { IngestionRunsPanel } from "@/components/dashboard/ingestion-runs-panel"
import { MediaStrip } from "@/components/dashboard/media-strip"
import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import { TopStatusBar } from "@/components/dashboard/top-status-bar"
import { getDashboardSnapshot, runIngest } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { DashboardSnapshot } from "@/lib/types"
import { cn } from "@/lib/utils"

export function DashboardShell({
  initialData,
  enableQueries = true,
}: {
  initialData: DashboardSnapshot
  enableQueries?: boolean
}) {
  const queryClient = useQueryClient()
  const [selectedSourceId, setSelectedSourceId] = useState(initialData.sources[0]?.id ?? "")
  const [detailOpen, setDetailOpen] = useState(false)

  const dashboardQuery = useQuery({
    queryKey: queryKeys.dashboardSnapshot,
    queryFn: getDashboardSnapshot,
    placeholderData: initialData,
    enabled: enableQueries,
    refetchInterval: 30_000,
  })

  const ingestMutation = useMutation({
    mutationFn: () => runIngest({}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSnapshot })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs })
      void queryClient.invalidateQueries({ queryKey: queryKeys.contentItems })
      void queryClient.invalidateQueries({ queryKey: queryKeys.media })
    },
  })

  const data = dashboardQuery.data ?? initialData
  const selectedSource = useMemo(
    () => data.sources.find((source) => source.id === selectedSourceId) ?? data.sources[0],
    [data.sources, selectedSourceId]
  )
  const connectionState = dashboardQuery.isError
    ? "unavailable"
    : dashboardQuery.isFetching && hasNoDashboardData(data)
      ? "checking"
      : "connected"

  const selectSource = (sourceId: string) => {
    setSelectedSourceId(sourceId)
    setDetailOpen(true)
  }

  return (
    <section aria-label="Ingestion dashboard" className="min-w-0 bg-slate-50 text-sm text-foreground">
      <div className={cn("grid min-w-0", selectedSource && "xl:grid-cols-[minmax(0,1fr)_440px]")}>
        <div className="min-w-0 bg-white">
          <TopStatusBar
            onRunIngest={() => ingestMutation.mutate()}
            isRunning={ingestMutation.isPending}
            connectionState={connectionState}
            lastRunLabel={data.runs[0]?.label ?? null}
          />
          <div className="min-w-0 space-y-4 p-4">
            {dashboardQuery.isError ? (
              <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                Backend data unavailable
              </div>
            ) : null}
            {dashboardQuery.isFetching && hasNoDashboardData(data) ? (
              <div role="status" className="rounded-md border bg-muted px-3 py-2 text-sm text-muted-foreground">
                Loading dashboard data
              </div>
            ) : null}
            <SourceHealthTable
              sources={data.sources}
              selectedSourceId={selectedSource?.id ?? ""}
              onSelectSource={selectSource}
            />
            <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
              <IngestionRunsPanel runs={data.runs} />
              <ContentQueuePanel items={data.queue} />
            </div>
            <MediaStrip media={data.media} />
          </div>
        </div>
        {selectedSource ? <SourceDetailPanel source={selectedSource} open={detailOpen} onOpenChange={setDetailOpen} /> : null}
      </div>
    </section>
  )
}

function hasNoDashboardData(data: DashboardSnapshot) {
  return !data.sources.length && !data.runs.length && !data.queue.length && !data.media.length
}
