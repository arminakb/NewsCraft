"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Database, Play } from "lucide-react"
import { useState } from "react"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import { Button } from "@/components/ui/button"
import { getSources, runIngest, seedSources } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { SourceSummary } from "@/lib/types"

export function SourcesPage({ initialSources }: { initialSources: SourceSummary[] }) {
  const queryClient = useQueryClient()
  const [selectedSourceId, setSelectedSourceId] = useState(initialSources[0]?.id ?? "")
  const [detailOpen, setDetailOpen] = useState(false)
  const sourcesQuery = useQuery({
    queryKey: queryKeys.sources,
    queryFn: getSources,
    initialData: initialSources,
    enabled: process.env.NODE_ENV !== "test",
  })
  const seedMutation = useMutation({
    mutationFn: seedSources,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  })
  const ingestMutation = useMutation({
    mutationFn: () => runIngest({}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  })
  const sources = sourcesQuery.data
  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? sources[0]

  return (
    <OperationsPageFrame
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
          counts={{
            all: sources.length,
            rss: sources.filter((source) => source.platform === "rss").length,
            telegram: sources.filter((source) => source.platform === "telegram_public").length,
          }}
          onSelectSource={(sourceId) => {
            setSelectedSourceId(sourceId)
            setDetailOpen(true)
          }}
        />
        {selectedSource ? <SourceDetailPanel source={selectedSource} open={detailOpen} onOpenChange={setDetailOpen} /> : null}
      </div>
    </OperationsPageFrame>
  )
}
