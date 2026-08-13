"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Database, Plus } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import {
  ALL_SOURCES_SCOPE,
  SourceCollectionsPanel,
  UNASSIGNED_SOURCES_SCOPE,
} from "@/components/dashboard/source-collections-panel"
import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import {
  AddSourceDialog,
  DeleteSourceDialog,
  type NewSourceInput,
} from "@/components/dashboard/source-management-dialogs"
import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import {
  checkSourceHealth,
  createSource,
  deleteSource as deleteSourceRequest,
  getSource,
  getSources,
  getSourcePage,
  seedSources,
  type SourcePage,
  type SourceSummaryList,
} from "@/features/operations/ingestion-api"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import { getApiErrorMessage } from "@/lib/http"
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
  const requestedScope = searchParams?.get("source_collection_id")
    ?? (searchParams?.get("unassigned") === "true" ? UNASSIGNED_SOURCES_SCOPE : ALL_SOURCES_SCOPE)
  const [selectedSourceId, setSelectedSourceId] = useState(requestedSourceId ?? initialSources[0]?.id ?? "")
  const [selectedScope, setSelectedScope] = useState(requestedScope)
  const [sourcePageOffset, setSourcePageOffset] = useState(0)
  const [detailOpen, setDetailOpen] = useState(Boolean(requestedSourceId))
  const [addedSources, setAddedSources] = useState<SourceSummary[]>([])
  const [deletedSourceIds, setDeletedSourceIds] = useState<string[]>([])
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<SourceSummary | null>(null)
  const [healthOverrides, setHealthOverrides] = useState<Record<string, Partial<SourceSummary>>>({})
  const [checkingSourceIds, setCheckingSourceIds] = useState<ReadonlySet<string>>(new Set())
  const [bulkChecking, setBulkChecking] = useState(false)
  const checkingSourceIdsRef = useRef(new Set<string>())
  const requestedScopeRef = useRef(requestedScope)
  const sourcesQuery = useQuery<SourceSummaryList | SourcePage>({
    queryKey: queryKeys.sourcesPage(selectedScope, sourcePageOffset),
    queryFn: ({ signal }) => selectedScope === ALL_SOURCES_SCOPE
      ? getSources({ limit: 50, offset: sourcePageOffset }, signal)
      : selectedScope === UNASSIGNED_SOURCES_SCOPE
        ? getSourcePage({ unassigned: true, limit: 50, offset: sourcePageOffset }, signal)
        : getSourcePage({ collectionId: selectedScope, limit: 50, offset: sourcePageOffset }, signal),
    placeholderData: selectedScope === ALL_SOURCES_SCOPE ? initialSources as SourceSummaryList : undefined,
    enabled: enableQueries,
    refetchInterval: (query) => {
      const data = query.state.data
      const rows = data ? (Array.isArray(data) ? data : data.items) : []
      return rows.some((source) => source.iconStatus === "pending" || source.iconStatus === "queued") ? 5_000 : false
    },
  })
  const seedMutation = useMutation({
    mutationFn: seedSources,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  })
  const pageData = sourcesQuery.data
  const fetchedSources = pageData
    ? Array.isArray(pageData) ? pageData : pageData.items
    : initialSources
  const sourceTotal = pageData
    ? Array.isArray(pageData) ? pageData.total : pageData.total
    : initialSources.length
  const sourceHasMore = pageData
    ? Array.isArray(pageData) ? pageData.hasMore : pageData.hasMore
    : false
  const baseSources = useMemo(
    () => selectedScope === ALL_SOURCES_SCOPE
      ? [
        ...addedSources,
        ...fetchedSources.filter((source) =>
          !deletedSourceIds.includes(source.id)
          && !addedSources.some((addedSource) => addedSource.id === source.id)
        ),
      ]
      : fetchedSources.filter((source) => !deletedSourceIds.includes(source.id)),
    [addedSources, deletedSourceIds, fetchedSources, selectedScope]
  )
  const sources = useMemo(
    () => baseSources.map((source) => ({
      ...source,
      ...healthOverrides[source.id],
    })),
    [baseSources, healthOverrides],
  )
  const createMutation = useMutation({
    mutationFn: createSource,
    onSuccess: (source) => {
      setAddedSources((current) => [
        source,
        ...current.filter((item) => item.id !== source.id),
      ])
      queryClient.setQueryData<SourceSummary[]>(queryKeys.sources, (current) =>
        current
          ? [source, ...current.filter((item) => item.id !== source.id)]
          : [source]
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      setSelectedSourceId(source.id)
      setDetailOpen(true)
      setAddDialogOpen(false)
      pushNotice({
        tone: "success",
        title: "Source added",
        message: `${source.name} is now available in source management.`,
      })
    },
    onError: (error) => {
      pushNotice({
        tone: "error",
        title: "Source creation failed",
        message: getApiErrorMessage(error, "Could not add source. Try again."),
      })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (source: SourceSummary) => deleteSourceRequest(source.id),
    onSuccess: (_, source) => {
      const remainingSources = sources.filter((item) => item.id !== source.id)
      setAddedSources((current) => current.filter((item) => item.id !== source.id))
      setDeletedSourceIds((current) =>
        current.includes(source.id) ? current : [...current, source.id]
      )
      queryClient.removeQueries({ queryKey: queryKeys.source(source.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      if (selectedSourceId === source.id) {
        setSelectedSourceId(remainingSources[0]?.id ?? "")
        setDetailOpen(false)
      }
      pushNotice({
        tone: "success",
        title: "Source deleted",
        message: `${source.name} was removed from source management.`,
      })
      setDeleteTarget(null)
    },
    onError: (error, source) => {
      pushNotice({
        tone: "error",
        title: "Source deletion failed",
        message: getApiErrorMessage(error, `Could not delete ${source.name}. Try again.`),
      })
    },
  })
  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? sources[0]
  const sourceDetailQuery = useQuery({
    queryKey: selectedSourceId ? queryKeys.source(selectedSourceId) : ["sources", "detail"],
    queryFn: () => getSource(selectedSourceId),
    enabled: Boolean(selectedSourceId) && enableQueries,
    placeholderData: selectedSource,
    refetchInterval: (query) => {
      const status = query.state.data?.iconStatus
      return status === "pending" || status === "queued" ? 5_000 : false
    },
  })
  const displayedSourceDetail = sourceDetailQuery.data
    ? { ...sourceDetailQuery.data, ...healthOverrides[sourceDetailQuery.data.id] }
    : selectedSource
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

  useEffect(() => {
    if (requestedScopeRef.current === requestedScope) return
    requestedScopeRef.current = requestedScope
    setSelectedScope(requestedScope)
    setSourcePageOffset(0)
    setSelectedSourceId("")
    setDetailOpen(false)
  }, [requestedScope])

  function addSource(input: NewSourceInput) {
    createMutation.mutate(input)
  }

  function openAddDialog() {
    createMutation.reset()
    setAddDialogOpen(true)
  }

  function selectSourceScope(scope: string) {
    if (scope === selectedScope) return
    setSelectedScope(scope)
    setSourcePageOffset(0)
    setSelectedSourceId("")
    setDetailOpen(false)
    const params = new URLSearchParams(searchParams?.toString() ?? "")
    params.delete("source")
    params.delete("source_collection_id")
    params.delete("unassigned")
    if (scope === UNASSIGNED_SOURCES_SCOPE) params.set("unassigned", "true")
    else if (scope !== ALL_SOURCES_SCOPE) params.set("source_collection_id", scope)
    const query = params.toString()
    window.history.pushState(null, "", query ? `/sources?${query}` : "/sources")
  }

  function closeAddDialog() {
    if (createMutation.isPending) return
    createMutation.reset()
    setAddDialogOpen(false)
  }

  function deleteSource() {
    if (!deleteTarget) return
    deleteMutation.mutate(deleteTarget)
  }

  function requestDelete(source: SourceSummary) {
    deleteMutation.reset()
    setDeleteTarget(source)
  }

  function closeDeleteDialog() {
    if (deleteMutation.isPending) return
    deleteMutation.reset()
    setDeleteTarget(null)
  }

  async function runHealthCheck(sourceId: string, announce = true) {
    if (checkingSourceIdsRef.current.has(sourceId)) return true
    checkingSourceIdsRef.current.add(sourceId)
    setCheckingSourceIds(new Set(checkingSourceIdsRef.current))
    try {
      const result = await checkSourceHealth(sourceId)
      const patch: Partial<SourceSummary> = {
        status: result.status,
        lastCheckedAt: result.lastCheckedAt,
        failureReason: result.failureReason,
      }
      setHealthOverrides((current) => ({
        ...current,
        [sourceId]: { ...current[sourceId], ...patch },
      }))
      queryClient.setQueryData<SourceSummary[]>(queryKeys.sources, (current) =>
        current?.map((source) => source.id === sourceId ? { ...source, ...patch } : source)
      )
      queryClient.setQueryData<SourceSummary>(queryKeys.source(sourceId), (current) =>
        current ? { ...current, ...patch } : current
      )
      if (announce) {
        pushNotice({
          tone: result.status === "healthy" ? "success" : "error",
          title: "Health check complete",
          message: result.status === "healthy"
            ? "Source is healthy."
            : result.failureReason ?? "Source is broken.",
          compact: true,
        })
      }
      return true
    } catch (error) {
      const message = getApiErrorMessage(error, "Health check failed. Try again.")
      setHealthOverrides((current) => ({
        ...current,
        [sourceId]: { ...current[sourceId], failureReason: message },
      }))
      if (announce) {
        pushNotice({
          tone: "error",
          title: "Health check failed",
          message,
          compact: true,
        })
      }
      return false
    } finally {
      checkingSourceIdsRef.current.delete(sourceId)
      setCheckingSourceIds(new Set(checkingSourceIdsRef.current))
    }
  }

  async function runAllHealthChecks() {
    if (bulkChecking || sources.length === 0) return
    setBulkChecking(true)
    let nextIndex = 0
    let failures = 0
    const workerCount = Math.min(4, sources.length)
    const workers = Array.from({ length: workerCount }, async () => {
      while (nextIndex < sources.length) {
        const source = sources[nextIndex]
        nextIndex += 1
        if (!(await runHealthCheck(source.id, false))) failures += 1
      }
    })
    await Promise.all(workers)
    setBulkChecking(false)
    pushNotice({
      tone: failures ? "error" : "success",
      title: failures ? "Source health checks finished with errors" : "Source health checks complete",
      message: failures
        ? `${sources.length - failures} of ${sources.length} sources checked successfully.`
        : `${sources.length} sources checked successfully.`,
      compact: true,
    })
  }

  return (
    <>
      <OperationsPageFrame
        enableQueries={enableQueries}
        title="Sources"
        subtitle="Manage RSS feeds and public Telegram channels."
        actions={
          <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
            <Button variant="outline" className="gap-2" onClick={() => seedMutation.mutate()} disabled={seedMutation.isPending}>
              <Database className="size-4" aria-hidden="true" />
              {seedMutation.isPending ? "Seeding" : "Seed sources"}
            </Button>
            <Button className="gap-2" onClick={openAddDialog}>
              <Plus className="size-4" aria-hidden="true" />
              Add source
            </Button>
          </div>
        }
      >
        <SourceCollectionsPanel
          enableQueries={enableQueries}
          onSelectScope={selectSourceScope}
          selectedScope={selectedScope}
        >
          {({ onStartIngestion }) => (
            <div className={detailOpen ? "grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)]" : "grid min-w-0"}>
              <div className="min-w-0">
                <SourceHealthTable
                  bulkChecking={bulkChecking}
                  checkingSourceIds={checkingSourceIds}
                  onCheckAll={() => void runAllHealthChecks()}
                  onCheckSource={(sourceId) => void runHealthCheck(sourceId)}
                  sources={sources}
                  selectedSourceId={selectedSource?.id ?? ""}
                  totalCount={sourceTotal}
                  pageOffset={sourcePageOffset}
                  pageSize={50}
                  hasMore={sourceHasMore}
                  onPageChange={(offset) => {
                    setSourcePageOffset(offset)
                    setSelectedSourceId("")
                    setDetailOpen(false)
                  }}
                  onDeleteSource={requestDelete}
                  onSelectSource={selectSource}
                  onStartIngestion={onStartIngestion}
                />
              </div>
              {detailOpen && displayedSourceDetail ? (
                <SourceDetailPanel source={displayedSourceDetail} open={detailOpen} onOpenChange={setDetailOpen} />
              ) : null}
            </div>
          )}
        </SourceCollectionsPanel>
      </OperationsPageFrame>
      <AddSourceDialog
        error={createMutation.isError ? getApiErrorMessage(createMutation.error, "Source creation failed.") : null}
        isSubmitting={createMutation.isPending}
        onClose={closeAddDialog}
        onSubmit={addSource}
        open={addDialogOpen}
      />
      <DeleteSourceDialog
        error={deleteMutation.isError ? getApiErrorMessage(deleteMutation.error, "Source deletion failed.") : null}
        isDeleting={deleteMutation.isPending}
        onClose={closeDeleteDialog}
        onConfirm={deleteSource}
        source={deleteTarget}
      />
    </>
  )
}
