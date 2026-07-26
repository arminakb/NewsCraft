"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Database, Play } from "lucide-react"
import { useState } from "react"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import { Button } from "@/components/ui/button"
import {
  getSource,
  getSources,
  runIngest,
  seedSources,
} from "@/features/operations/ingestion-api"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import { queryKeys } from "@/lib/query-keys"

export function SourcesPage({
  initialSources = [],
  enableQueries = true,
}: {
  initialSources?: SourceSummary[]
  enableQueries?: boolean
}) {
  const queryClient = useQueryClient()
  const [selectedSourceId, setSelectedSourceId] = useState(initialSources[0]?.id ?? "")
  const [detailOpen, setDetailOpen] = useState(false)
  const sourcesQuery = useQuery({
    queryKey: queryKeys.sources,
    queryFn: getSources,
    placeholderData: initialSources,
    enabled: enableQueries,
  })
  const seedMutation = useMutation({
    mutationFn: seedSources,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  })
  const ingestMutation = useMutation({
    mutationFn: () => runIngest({}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  })
  const sources = sourcesQuery.data ?? initialSources
  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? sources[0]
  const sourceDetailQuery = useQuery({
    queryKey: selectedSourceId ? queryKeys.source(selectedSourceId) : ["sources", "detail"],
    queryFn: () => getSource(selectedSourceId),
    enabled: Boolean(selectedSourceId) && enableQueries,
    placeholderData: selectedSource,
  })

  return (
    <OperationsPageFrame
      enableQueries={enableQueries}
      title="Sources"
      subtitle="Manage RSS feeds and public Telegram channels."
      actions={
        <>
          <Button variant="outline" className="h-9 gap-2" onClick={() => seedMutation.mutate()} disabled={seedMutation.isPending}>
            <Database className="size-4" aria-hidden="true" />
            {seedMutation.isPending ? "Seeding" : "Seed sources"}
          </Button>
          <Button className="h-9 gap-2" onClick={() => ingestMutation.mutate()} disabled={ingestMutation.isPending}>
            <Play className="size-4" aria-hidden="true" />
            {ingestMutation.isPending ? "Running" : "Run ingest"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <SourceHealthTable
          sources={sources}
          selectedSourceId={selectedSource?.id ?? ""}
          onSelectSource={(sourceId) => {
            setSelectedSourceId(sourceId)
            setDetailOpen(true)
          }}
        />
        {sourceDetailQuery.data ? (
          <SourceDetailPanel source={sourceDetailQuery.data} open={detailOpen} onOpenChange={setDetailOpen} />
        ) : null}
      </div>
    </OperationsPageFrame>
  )
}
