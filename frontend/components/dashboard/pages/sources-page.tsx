"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Database, Plus } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import {
  AddSourceDialog,
  DeleteSourceDialog,
  type NewSourceInput,
} from "@/components/dashboard/source-management-dialogs"
import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import {
  getSource,
  getSources,
  seedSources,
} from "@/features/operations/ingestion-api"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import { queryKeys } from "@/lib/query-keys"

export function SourcesPage({
  initialSources = [],
  enableQueries = true,
  initialSourceId = null,
}: {
  initialSources?: SourceSummary[]
  enableQueries?: boolean
  initialSourceId?: string | null
}) {
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const requestedSourceId = searchParams?.get("source") ?? initialSourceId
  const [selectedSourceId, setSelectedSourceId] = useState(requestedSourceId ?? initialSources[0]?.id ?? "")
  const [detailOpen, setDetailOpen] = useState(Boolean(requestedSourceId))
  const [addedSources, setAddedSources] = useState<SourceSummary[]>([])
  const [deletedSourceIds, setDeletedSourceIds] = useState<string[]>([])
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SourceSummary | null>(null)
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
  const fetchedSources = sourcesQuery.data ?? initialSources
  const sources = useMemo(
    () => [
      ...addedSources,
      ...fetchedSources.filter((source) =>
        !deletedSourceIds.includes(source.id)
        && !addedSources.some((addedSource) => addedSource.id === source.id)
      ),
    ],
    [addedSources, deletedSourceIds, fetchedSources]
  )
  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? sources[0]
  const selectedSourceIsLocal = addedSources.some((source) => source.id === selectedSourceId)
  const sourceDetailQuery = useQuery({
    queryKey: selectedSourceId ? queryKeys.source(selectedSourceId) : ["sources", "detail"],
    queryFn: () => getSource(selectedSourceId),
    enabled: Boolean(selectedSourceId) && enableQueries && !selectedSourceIsLocal,
    placeholderData: selectedSource,
  })
  const selectSource = useCallback((sourceId: string) => {
    setSelectedSourceId(sourceId)
    setDetailOpen(true)
  }, [])

  useEffect(() => {
    if (!searchParams) return
    const sourceId = searchParams?.get("source")
    if (sourceId) {
      setSelectedSourceId(sourceId)
      setDetailOpen(true)
    }
  }, [searchParams])

  function addSource(input: NewSourceInput) {
    const source = createLocalSource(input)
    setAddedSources((current) => [source, ...current])
    setSelectedSourceId(source.id)
    setDetailOpen(true)
    setAddDialogOpen(false)
    pushNotice({
      tone: "success",
      title: "Source added",
      message: `${source.name} is now available in source management.`,
    })
  }

  function deleteSource() {
    if (!deleteTarget) return
    const remainingSources = sources.filter((source) => source.id !== deleteTarget.id)
    setAddedSources((current) => current.filter((source) => source.id !== deleteTarget.id))
    setDeletedSourceIds((current) =>
      current.includes(deleteTarget.id) ? current : [...current, deleteTarget.id]
    )
    if (selectedSourceId === deleteTarget.id) {
      setSelectedSourceId(remainingSources[0]?.id ?? "")
      setDetailOpen(false)
    }
    pushNotice({
      tone: "success",
      title: "Source deleted",
      message: `${deleteTarget.name} was removed from source management.`,
    })
    setDeleteTarget(null)
  }

  return (
    <>
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
            <Button className="h-9 gap-2" onClick={() => setAddDialogOpen(true)}>
              <Plus className="size-4" aria-hidden="true" />
              Add source
            </Button>
          </>
        }
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
          <SourceHealthTable
            sources={sources}
            selectedSourceId={selectedSource?.id ?? ""}
            onDeleteSource={setDeleteTarget}
            onSelectSource={selectSource}
          />
          {sourceDetailQuery.data ? (
            <SourceDetailPanel source={sourceDetailQuery.data} open={detailOpen} onOpenChange={setDetailOpen} />
          ) : null}
        </div>
      </OperationsPageFrame>
      <AddSourceDialog onClose={() => setAddDialogOpen(false)} onSubmit={addSource} open={addDialogOpen} />
      <DeleteSourceDialog onClose={() => setDeleteTarget(null)} onConfirm={deleteSource} source={deleteTarget} />
    </>
  )
}

function createLocalSource(input: NewSourceInput): SourceSummary {
  const now = new Date()
  return {
    id: `local-${crypto.randomUUID()}`,
    platform: input.platform,
    name: input.name,
    url: input.url,
    category: input.category,
    language: input.language,
    status: "unknown",
    items24h: 0,
    new24h: 0,
    failed24h: 0,
    lastSuccess: null,
    fetchIntervalMinutes: input.fetchIntervalMinutes,
    totalItems: 0,
    media24h: 0,
    addedAt: new Intl.DateTimeFormat("en-CA", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(now).replace(",", ""),
  }
}
