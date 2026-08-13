"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ChevronLeft,
  ChevronRight,
  Database,
  Folder,
  FolderOpen,
  FolderPlus,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  Search,
  Settings2,
  Trash2,
  Users,
  X,
} from "lucide-react"
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react"

import { CollectionContextMenu } from "@/components/collections/collection-context-menu"
import { CollectionNavigationItem } from "@/components/collections/collection-navigation"
import { Badge } from "@/components/ui/badge"
import { SourceIcon } from "@/components/dashboard/source-icon"
import { CollectionRunHistory } from "@/components/dashboard/source-collection-run-history"
import { Button } from "@/components/ui/button"
import { Checkbox, Radio } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress"
import {
  addSourcesToCollection,
  createSourceCollection,
  deleteSourceCollection,
  getSourceCollectionRun,
  getSourceCollectionRuns,
  getSourceCollectionSources,
  getSourceCollections,
  getSourcePage,
  getUnassignedSources,
  removeSourcesFromCollection,
  stopSourceCollectionContinuous,
  startSourceCollectionIngest,
  updateSourceCollection,
  type SourceCollectionRun,
  type SourceCollectionIngestMode,
  type SourceCollectionSummary,
  type SourcePage,
} from "@/features/operations/ingestion-api"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import { getApiErrorMessage } from "@/lib/http"
import { formatInTimeZone } from "@/lib/date-time"
import { queryKeys } from "@/lib/query-keys"

export const ALL_SOURCES_SCOPE = "all"
export const UNASSIGNED_SOURCES_SCOPE = "unassigned"

type SourceCollectionsPanelProps = {
  children: (actions: { onStartIngestion: () => void }) => React.ReactNode
  selectedScope: string
  onSelectScope: (scope: string) => void
}

export function SourceCollectionsPanel({
  children,
  selectedScope,
  onSelectScope,
}: SourceCollectionsPanelProps) {
  const queryClient = useQueryClient()
  const [formTarget, setFormTarget] = useState<SourceCollectionSummary | null | undefined>(undefined)
  const [manageTarget, setManageTarget] = useState<SourceCollectionSummary | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SourceCollectionSummary | null>(null)
  const [ingestDialogOpen, setIngestDialogOpen] = useState(false)
  const [ingestSelection, setIngestSelection] = useState("")
  const [ingestMode, setIngestMode] = useState<SourceCollectionIngestMode>("once")
  const [startedRun, setStartedRun] = useState<{ collectionId: string; runId: string } | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const contextTriggerRef = useRef<HTMLButtonElement | null>(null)

  const restoreContextTrigger = () => {
    const trigger = contextTriggerRef.current
    contextTriggerRef.current = null
    queueMicrotask(() => trigger?.isConnected && trigger.focus())
  }

  const collectionsQuery = useQuery({
    queryKey: queryKeys.sourceCollections,
    queryFn: ({ signal }) => getSourceCollections(signal),
    staleTime: 5_000,
    refetchInterval: (query) => query.state.data?.some((collection) =>
      ["starting", "running", "stopping"].includes(collection.continuousStatus ?? ""),
    ) ? 5_000 : false,
  })
  const collections = collectionsQuery.data ?? []
  const selectedCollection = collections.find((collection) => collection.id === selectedScope) ?? null
  const allSourcesCountQuery = useQuery({
    queryKey: ["sources", "count"],
    queryFn: ({ signal }) => getSourcePage({ limit: 1, offset: 0 }, signal),
    staleTime: 10_000,
  })
  const unassignedCountQuery = useQuery({
    queryKey: ["source-collections", "unassigned", "count"],
    queryFn: ({ signal }) => getUnassignedSources({ limit: 1, offset: 0 }, signal),
    staleTime: 10_000,
  })

  const refreshCollections = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCollections })
    void queryClient.invalidateQueries({ queryKey: queryKeys.sources })
  }

  const createMutation = useMutation({
    mutationFn: createSourceCollection,
    onSuccess: (collection) => {
      queryClient.setQueryData<SourceCollectionSummary[]>(queryKeys.sourceCollections, (current) => [
        collection,
        ...(current ?? []).filter((item) => item.id !== collection.id),
      ])
      setFormTarget(undefined)
      restoreContextTrigger()
      onSelectScope(collection.id)
      setActionError(null)
    },
    onError: (error) => setActionError(getApiErrorMessage(error, "Could not create the Source Collection.")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: { name?: string; description?: string | null } }) =>
      updateSourceCollection(id, input),
    onSuccess: (collection) => {
      queryClient.setQueryData<SourceCollectionSummary[]>(queryKeys.sourceCollections, (current) =>
        (current ?? []).map((item) => item.id === collection.id ? collection : item),
      )
      setFormTarget(undefined)
      restoreContextTrigger()
      setActionError(null)
    },
    onError: (error) => setActionError(getApiErrorMessage(error, "Could not update the Source Collection.")),
  })

  const deleteMutation = useMutation({
    mutationFn: (collection: SourceCollectionSummary) => deleteSourceCollection(collection.id),
    onSuccess: (_, collection) => {
      queryClient.setQueryData<SourceCollectionSummary[]>(queryKeys.sourceCollections, (current) =>
        (current ?? []).filter((item) => item.id !== collection.id),
      )
      queryClient.removeQueries({ queryKey: queryKeys.sourceCollection(collection.id) })
      setDeleteTarget(null)
      if (selectedScope === collection.id) onSelectScope(ALL_SOURCES_SCOPE)
      setActionError(null)
    },
    onError: (error) => setActionError(getApiErrorMessage(error, "Could not delete the Source Collection.")),
  })

  const startMutation = useMutation({
    mutationFn: ({ collectionId, mode }: { collectionId: string; mode: SourceCollectionIngestMode }) =>
      startSourceCollectionIngest(collectionId, newRequestId(), mode),
    onSuccess: (result) => {
      if (result.mode === "once" && result.runId) {
        setStartedRun({ collectionId: result.sourceCollectionId, runId: result.runId })
      } else {
        setStartedRun(null)
      }
      setIngestDialogOpen(false)
      setIngestSelection("")
      onSelectScope(result.sourceCollectionId)
      refreshCollections()
      setActionError(null)
    },
    onError: (error) => setActionError(getApiErrorMessage(error, "Could not start collection ingestion.")),
  })

  const stopMutation = useMutation({
    mutationFn: (collectionId: string) => stopSourceCollectionContinuous(collectionId),
    onSuccess: () => {
      refreshCollections()
      setActionError(null)
    },
    onError: (error) => setActionError(getApiErrorMessage(error, "Could not stop continuous ingestion.")),
  })

  const activeRunId = selectedCollection?.activeIngestRunId
    ?? (startedRun && startedRun.collectionId === selectedCollection?.id ? startedRun.runId : null)
  const activeRunQuery = useQuery({
    queryKey: activeRunId && selectedCollection
      ? queryKeys.sourceCollectionRun(selectedCollection.id, activeRunId)
      : ["source-collections", "run", "idle"],
    queryFn: ({ signal }) => getSourceCollectionRun(selectedCollection!.id, activeRunId!, signal),
    enabled: Boolean(selectedCollection && activeRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && !["queued", "running"].includes(status) ? false : 5_000
    },
  })
  const runHistoryQuery = useQuery({
    queryKey: selectedCollection
      ? queryKeys.sourceCollectionRuns(selectedCollection.id, 3, 0)
      : ["source-collections", "runs", "idle"],
    queryFn: ({ signal }) => getSourceCollectionRuns(
      selectedCollection!.id,
      { limit: 3, offset: 0 },
      signal,
    ),
    enabled: Boolean(selectedCollection),
    staleTime: 5_000,
  })

  useEffect(() => {
    const run = activeRunQuery.data
    if (!run || ["queued", "running"].includes(run.status)) return
    setStartedRun((current) => current?.runId === run.id ? null : current)
    if (run.sourceCollectionId) {
      void queryClient.invalidateQueries({
        queryKey: ["source-collections", run.sourceCollectionId, "runs"],
      })
    }
    refreshCollections()
  }, [activeRunQuery.data])

  const selectedScopeIsCollection = Boolean(selectedCollection)
  const formOpen = formTarget !== undefined
  const openIngestDialog = () => {
    setIngestSelection("")
    setIngestMode("once")
    setActionError(null)
    setIngestDialogOpen(true)
  }

  return (
    <>
      <div className="min-w-0 min-[900px]:grid min-[900px]:grid-cols-[216px_minmax(0,1fr)] min-[900px]:items-start lg:grid-cols-[224px_minmax(0,1fr)]">
        <aside
          aria-label="Source Collections"
          className="sticky top-0 z-20 min-w-0 overflow-x-auto border-b border-border/50 bg-card/95 backdrop-blur min-[900px]:top-4 min-[900px]:max-h-[calc(100vh-2rem)] min-[900px]:overflow-x-hidden min-[900px]:overflow-y-auto min-[900px]:rounded-lg min-[900px]:border min-[900px]:bg-card/50 min-[900px]:backdrop-blur-none"
        >
          <nav aria-label="Source collection filters" className="flex min-w-max items-center gap-1 p-2 min-[900px]:block min-[900px]:min-w-0 min-[900px]:p-3">
            <CollectionNavigationItem
              active={selectedScope === ALL_SOURCES_SCOPE}
              count={allSourcesCountQuery.data?.total ?? null}
              countLabel={(count) => `${count} ${count === 1 ? "source" : "sources"}`}
              icon={Database}
              label="All Sources"
              onClick={() => onSelectScope(ALL_SOURCES_SCOPE)}
            />
            <div className="min-[900px]:mt-1">
              <CollectionNavigationItem
                active={selectedScope === UNASSIGNED_SOURCES_SCOPE}
                count={unassignedCountQuery.data?.total ?? null}
                countLabel={(count) => `${count} unassigned ${count === 1 ? "source" : "sources"}`}
                icon={Users}
                label="Unassigned"
                onClick={() => onSelectScope(UNASSIGNED_SOURCES_SCOPE)}
              />
            </div>

            <div className="flex items-center justify-between gap-2 px-1 min-[900px]:mt-5 min-[900px]:px-2">
              <h2 className="hidden text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground min-[900px]:block">
                Collections
              </h2>
              <Button
                aria-label="Create new Source Collection"
                className="size-8 min-[900px]:min-h-8 min-[900px]:min-w-8"
                disabled={collectionsQuery.isPending || collectionsQuery.isError}
                onClick={() => {
                  contextTriggerRef.current = null
                  setActionError(null)
                  setFormTarget(null)
                }}
                size="icon"
                title="New Source Collection"
                type="button"
                variant="ghost"
              >
                <FolderPlus className="size-4" aria-hidden="true" />
              </Button>
            </div>

            <div className="min-[900px]:mt-2">
              {collectionsQuery.isLoading ? (
                <div aria-label="Loading Source Collections" className="flex items-center gap-2 px-2 py-1 min-[900px]:block min-[900px]:space-y-2" role="status">
                  <span className="sr-only">Loading Source Collections</span>
                  {[0, 1, 2].map((item) => (
                    <div aria-hidden="true" className="flex h-10 w-24 animate-pulse items-center gap-2 motion-reduce:animate-none min-[900px]:w-auto" key={item}>
                      <span className="size-4 rounded bg-muted" />
                      <span className="h-3 w-3/5 rounded bg-muted" />
                    </div>
                  ))}
                </div>
              ) : null}
              {collectionsQuery.isError ? (
                <div className="flex items-center gap-2 rounded-lg border bg-background p-2 min-[900px]:block min-[900px]:space-y-2 min-[900px]:p-3">
                  <p className="text-xs text-destructive" role="alert">{getApiErrorMessage(collectionsQuery.error, "Collections are unavailable.")}</p>
                  <Button className="min-h-9 w-full" onClick={() => void collectionsQuery.refetch()} size="sm" variant="outline">Retry</Button>
                </div>
              ) : null}
              {!collectionsQuery.isPending && !collectionsQuery.isError && collections.length === 0 ? (
                <p className="whitespace-nowrap px-2 py-3 text-xs leading-5 text-muted-foreground">No Source Collections yet.</p>
              ) : null}
              {!collectionsQuery.isPending && !collectionsQuery.isError && collections.length ? (
                <ul className="flex items-center gap-1 min-[900px]:block min-[900px]:space-y-1">
                  {collections.map((collection) => {
                    const active = selectedScope === collection.id
                    return (
                      <li className="min-w-0 shrink-0" key={collection.id}>
                        <CollectionContextMenu
                          actions={[
                            {
                              icon: Pencil,
                              label: "Edit details",
                              onSelect: (trigger) => {
                                contextTriggerRef.current = trigger
                                setActionError(null)
                                setFormTarget(collection)
                              },
                            },
                            {
                              icon: Settings2,
                              label: "Manage sources",
                              onSelect: (trigger) => {
                                contextTriggerRef.current = trigger
                                setManageTarget(collection)
                              },
                            },
                            {
                              destructive: true,
                              icon: Trash2,
                              label: "Delete",
                              onSelect: (trigger) => {
                                contextTriggerRef.current = trigger
                                setDeleteTarget(collection)
                              },
                            },
                          ]}
                          label={`Manage ${collection.name}`}
                        >
                          {(contextProps) => (
                            <CollectionNavigationItem
                              {...contextProps}
                              active={active}
                              count={collection.sourceCount}
                              countLabel={(count) => `${count} ${count === 1 ? "source" : "sources"}`}
                              icon={active ? FolderOpen : Folder}
                              label={collection.name}
                              onClick={() => onSelectScope(collection.id)}
                              status={collection.activeIngestStatus ? <span className="size-1.5 shrink-0 rounded-full bg-warning" aria-label="Ingestion active" /> : undefined}
                            />
                          )}
                        </CollectionContextMenu>
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </div>

          </nav>
        </aside>

        <div className="min-w-0 space-y-4 pt-4 min-[900px]:pl-4 min-[900px]:pt-0 lg:pl-5">
          {actionError ? (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-[var(--error-surface)] px-3 py-2 text-sm text-destructive" role="alert">
              <X className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>{actionError}</span>
            </div>
          ) : null}

          {selectedCollection ? (
            <section aria-label={`${selectedCollection.name} Source Collection`} className="rounded-lg border border-border/70 bg-card/60 p-3 shadow-xs">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="truncate font-medium">{selectedCollection.name}</h3>
                    <Badge variant="neutral">
                      {selectedCollection.sourceCount}/{selectedCollection.maximumSources} sources
                    </Badge>
                    {selectedCollection.activeIngestStatus ? (
                      <Badge variant="warning">Ingestion {selectedCollection.activeIngestStatus}</Badge>
                    ) : null}
                    {selectedCollection.continuousStatus ? (
                      <Badge variant={isActiveContinuousStatus(selectedCollection.continuousStatus) ? "warning" : "neutral"}>
                        Continuous {selectedCollection.continuousStatus}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {selectedCollection.description || "No description added."}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    className="gap-1.5"
                    onClick={() => {
                      contextTriggerRef.current = null
                      setManageTarget(selectedCollection)
                    }}
                    type="button"
                    variant="outline"
                  >
                    <Settings2 className="size-4" aria-hidden="true" />
                    Manage sources
                  </Button>
                  <Button
                    aria-label={`Edit ${selectedCollection.name}`}
                    onClick={() => {
                      contextTriggerRef.current = null
                      setActionError(null)
                      setFormTarget(selectedCollection)
                    }}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <Pencil className="size-4" aria-hidden="true" />
                  </Button>
                </div>
              </div>
              {selectedCollection.sourceCount === 0 ? (
                <p className="mt-3 text-sm text-warning">Run once needs at least one source. Continuous mode can wait for sources.</p>
              ) : null}
              {activeRunQuery.data ? <CollectionRunProgress run={activeRunQuery.data} /> : null}
              {selectedCollection.continuousSubscriptionId ? (
                <ContinuousSubscriptionStatus
                  collection={selectedCollection}
                  isStopping={stopMutation.isPending}
                  onStop={() => stopMutation.mutate(selectedCollection.id)}
                />
              ) : null}
              {runHistoryQuery.isSuccess ? (
                <CollectionRunHistory
                  collectionId={selectedCollection.id}
                  collectionName={selectedCollection.name}
                  hasMore={runHistoryQuery.data.hasMore}
                  runs={runHistoryQuery.data.items}
                />
              ) : null}
            </section>
          ) : null}
          {!selectedScopeIsCollection && selectedScope === UNASSIGNED_SOURCES_SCOPE ? (
            <p className="rounded-lg border border-border/70 bg-muted/25 px-3 py-2 text-sm text-muted-foreground">Showing sources that are not assigned to any Source Collection.</p>
          ) : null}
          {children({ onStartIngestion: openIngestDialog })}
        </div>
      </div>

      <CollectionFormDialog
        collection={formTarget ?? null}
        error={createMutation.isError || updateMutation.isError ? actionError : null}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        onClose={() => {
          if (!createMutation.isPending && !updateMutation.isPending) {
            setFormTarget(undefined)
            restoreContextTrigger()
          }
        }}
        onDelete={formTarget && formTarget !== null ? () => {
          setDeleteTarget(formTarget)
          setFormTarget(undefined)
        } : undefined}
        onSubmit={(input) => {
          if (formTarget) {
            updateMutation.mutate({ id: formTarget.id, input })
          } else {
            createMutation.mutate({ name: input.name ?? "", description: input.description })
          }
        }}
        open={formOpen}
      />

      <CollectionIngestDialog
        collections={collections}
        error={startMutation.isError ? actionError : null}
        isSubmitting={startMutation.isPending}
        onClose={() => {
          if (!startMutation.isPending) setIngestDialogOpen(false)
        }}
        onSelectionChange={setIngestSelection}
        onModeChange={setIngestMode}
        onSubmit={(mode) => ingestSelection && startMutation.mutate({ collectionId: ingestSelection, mode })}
        open={ingestDialogOpen}
        mode={ingestMode}
        selectedId={ingestSelection}
      />

      {manageTarget ? (
        <CollectionManagerDialog
          collection={manageTarget}
          onChanged={refreshCollections}
          onClose={() => {
            setManageTarget(null)
            restoreContextTrigger()
          }}
          open
        />
      ) : null}

      <Dialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null)
            restoreContextTrigger()
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Source Collection?</DialogTitle>
            <DialogDescription>
              {deleteTarget ? `Delete “${deleteTarget.name}”? Sources will stay available; only memberships are removed.` : ""}
            </DialogDescription>
          </DialogHeader>
          {actionError ? <div className="text-sm text-destructive" role="alert">{actionError}</div> : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" type="button">Cancel</Button>} />
            <Button
              disabled={deleteMutation.isPending || !deleteTarget}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
              type="button"
              variant="destructive"
            >
              {deleteMutation.isPending ? "Deleting" : "Delete collection"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function CollectionIngestDialog({
  collections,
  error,
  isSubmitting,
  mode,
  onClose,
  onModeChange,
  onSelectionChange,
  onSubmit,
  open,
  selectedId,
}: {
  collections: SourceCollectionSummary[]
  error: string | null
  isSubmitting: boolean
  mode: SourceCollectionIngestMode
  onClose: () => void
  onModeChange: (mode: SourceCollectionIngestMode) => void
  onSelectionChange: (id: string) => void
  onSubmit: (mode: SourceCollectionIngestMode) => void
  open: boolean
  selectedId: string
}) {
  const selected = collections.find((collection) => collection.id === selectedId) ?? null
  const active = Boolean(selected?.activeIngestRunId)
  const continuousActive = isActiveContinuousStatus(selected?.continuousStatus)
  const empty = selected?.sourceCount === 0
  const blocked = isSubmitting || !selected || active || continuousActive || (mode === "once" && empty)
  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Start ingestion</DialogTitle>
          <DialogDescription>
            Select exactly one Source Collection. Only its snapshotted sources will be processed.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-source-collection">Source Collection</label>
            <Select
              id="ingest-source-collection"
              onChange={(event) => onSelectionChange(event.target.value)}
              value={selectedId}
            >
              <option value="">Select a Source Collection</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name} · {collection.sourceCount}/{collection.maximumSources} sources
                </option>
              ))}
            </Select>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Ingestion mode</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors ${mode === "once" ? "border-primary/50 bg-primary/5" : "border-border/70 hover:bg-muted/40"}`}>
                <Radio
                  aria-describedby="run-once-help"
                  checked={mode === "once"}
                  name="source-collection-ingestion-mode"
                  onChange={() => onModeChange("once")}
                  value="once"
                />
                <span>
                  <span className="block text-sm font-medium">Run once</span>
                  <span className="block text-xs text-muted-foreground" id="run-once-help">Fetch the current source snapshot once.</span>
                </span>
              </label>
              <label className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 transition-colors ${mode === "continuous" ? "border-primary/50 bg-primary/5" : "border-border/70 hover:bg-muted/40"}`}>
                <Radio
                  aria-describedby="continuous-help"
                  checked={mode === "continuous"}
                  name="source-collection-ingestion-mode"
                  onChange={() => onModeChange("continuous")}
                  value="continuous"
                />
                <span>
                  <span className="block text-sm font-medium">Continuous</span>
                  <span className="block text-xs text-muted-foreground" id="continuous-help">Checks every {selected?.continuousIntervalMinutes ?? 15} minutes.</span>
                </span>
              </label>
            </div>
          </fieldset>
          {selected ? (
            <div className="rounded-md border border-border/70 bg-muted/25 px-3 py-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{selected.name}</span>
                <Badge variant={empty ? "warning" : active ? "warning" : "success"}>
                  {selected.sourceCount}/{selected.maximumSources} sources
                </Badge>
              </div>
              <p className="mt-1 text-muted-foreground">
                {continuousActive
                  ? "Continuous ingestion is already active for this Source Collection."
                  : active
                    ? "An ingestion run is already active for this Source Collection."
                    : mode === "continuous"
                      ? "NewsCraft will continue checking this collection for new items until you stop it."
                      : empty
                        ? "This Source Collection is empty. Add sources before running once."
                        : "A new run will use the current membership snapshot."}
              </p>
            </div>
          ) : (
            <p className="rounded-md border border-border/70 bg-muted/25 px-3 py-3 text-sm text-muted-foreground">
              No Source Collection selected.
            </p>
          )}
          {error ? <div className="text-sm text-destructive" role="alert">{error}</div> : null}
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" type="button">Cancel</Button>} />
          <Button
            disabled={blocked}
            onClick={() => onSubmit(mode)}
            type="button"
          >
            {isSubmitting ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Play className="size-4" aria-hidden="true" />}
            {isSubmitting ? "Starting" : mode === "continuous" ? "Start continuous" : "Start ingestion"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CollectionRunProgress({ run }: { run: SourceCollectionRun }) {
  const { timezone } = useDateTime()
  const progress = run.sourceCount ? Math.round((run.processedCount / run.sourceCount) * 100) : 0
  const terminal = !["queued", "running"].includes(run.status)
  const remaining = Math.max(0, run.sourceCount - run.processedCount)
  return (
    <div className="mt-4 rounded-md border border-border/70 bg-card px-3 py-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Ingestion progress</span>
        <Badge variant={terminal && run.failureCount ? "warning" : terminal ? "success" : "neutral"}>
          {run.status}
        </Badge>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {run.processedCount} of {run.sourceCount} sources
        </span>
      </div>
      <Progress className="mt-3" value={progress} aria-label={`${progress}% of sources processed`}>
        <ProgressLabel className="sr-only">Source ingestion progress</ProgressLabel>
        <ProgressValue className="sr-only" />
      </Progress>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{run.successCount} succeeded</span>
        <span className={run.failureCount ? "text-destructive" : ""}>{run.failureCount} failed</span>
        {run.skippedCount ? <span>{run.skippedCount} skipped</span> : null}
        {!terminal ? <span>{remaining} remaining</span> : null}
        <span>Started {formatInTimeZone(run.startedAt, timezone)}</span>
        {run.completedAt ? <span>Completed {formatInTimeZone(run.completedAt, timezone)}</span> : null}
        {run.error ? <span className="text-destructive">{run.error}</span> : null}
      </div>
    </div>
  )
}

function ContinuousSubscriptionStatus({
  collection,
  isStopping,
  onStop,
}: {
  collection: SourceCollectionSummary
  isStopping: boolean
  onStop: () => void
}) {
  const { timezone } = useDateTime()
  const status = collection.continuousStatus ?? "unknown"
  const currentCycle = collection.continuousCurrentCycleRunId || collection.continuousCurrentCycleJobId
    ? collection.activeIngestStatus ?? "queued"
    : null
  const waitingForSources = isActiveContinuousStatus(status)
    && (collection.sourceCount === 0 || collection.continuousLastCycleStatus === "waiting_for_sources")
  return (
    <div className="mt-4 rounded-md border border-primary/20 bg-primary/5 px-3 py-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Continuous ingestion</span>
        <Badge variant={isActiveContinuousStatus(status) ? "success" : status === "error" ? "warning" : "neutral"}>
          {formatContinuousStatus(status)}
        </Badge>
        <span className="text-xs text-muted-foreground">
          {collection.continuousCycleCount ?? 0} cycles
        </span>
        {isActiveContinuousStatus(status) ? (
          <Button
            className="ml-auto"
            disabled={isStopping || status === "stopping"}
            onClick={onStop}
            size="sm"
            type="button"
            variant="outline"
          >
            {isStopping || status === "stopping" ? "Stopping" : "Stop"}
          </Button>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{collection.sourceCount}/{collection.maximumSources} sources</span>
        {currentCycle ? <span>Current cycle: {currentCycle}</span> : null}
        {collection.continuousLastCycleAt ? <span>Last cycle {formatInTimeZone(collection.continuousLastCycleAt, timezone)}</span> : null}
        {collection.continuousNextCycleAt ? <span>Next cycle {formatInTimeZone(collection.continuousNextCycleAt, timezone)}</span> : null}
      </div>
      {waitingForSources ? (
        <p className="mt-2 text-xs text-warning">Waiting for sources. The subscription stays active and the next cycle will use the current membership.</p>
      ) : null}
      {collection.continuousLastError ? (
        <p className="mt-2 text-xs text-destructive" role="alert">{collection.continuousLastError}</p>
      ) : null}
    </div>
  )
}

function CollectionFormDialog({
  collection,
  error,
  isSubmitting,
  onClose,
  onDelete,
  onSubmit,
  open,
}: {
  collection: SourceCollectionSummary | null
  error: string | null
  isSubmitting: boolean
  onClose: () => void
  onDelete?: () => void
  onSubmit: (input: { name?: string; description?: string | null }) => void
  open: boolean
}) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")

  useEffect(() => {
    if (!open) return
    setName(collection?.name ?? "")
    setDescription(collection?.description ?? "")
  }, [collection, open])

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{collection ? "Edit Source Collection" : "New Source Collection"}</DialogTitle>
          <DialogDescription>
            Give the collection a clear operational name. Membership changes are managed separately.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            onSubmit({ name: name.trim(), description: description.trim() || null })
          }}
        >
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="source-collection-name">Name</label>
            <Input
              autoFocus
              id="source-collection-name"
              maxLength={60}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Morning News"
              required
              value={name}
            />
            <p className="text-xs text-muted-foreground">1–60 characters. Names are unique, case-insensitive.</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="source-collection-description">Description</label>
            <Textarea
              id="source-collection-description"
              maxLength={500}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What is this collection used for?"
              value={description}
            />
          </div>
          {error ? <div className="text-sm text-destructive" role="alert">{error}</div> : null}
          <DialogFooter className="justify-between">
            <div>
              {onDelete ? (
                <Button className="gap-1.5" onClick={onDelete} type="button" variant="destructive">
                  <Trash2 className="size-4" aria-hidden="true" />
                  Delete
                </Button>
              ) : null}
            </div>
            <div className="flex gap-2">
              <DialogClose render={<Button variant="outline" type="button">Cancel</Button>} />
              <Button disabled={isSubmitting || !name.trim()} type="submit">
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
                {collection ? "Save changes" : "Create collection"}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CollectionManagerDialog({
  collection,
  onChanged,
  onClose,
  open,
}: {
  collection: SourceCollectionSummary
  onChanged: () => void
  onClose: () => void
  open: boolean
}) {
  const queryClient = useQueryClient()
  const [memberOffset, setMemberOffset] = useState(0)
  const [availableOffset, setAvailableOffset] = useState(0)
  const [availableSearch, setAvailableSearch] = useState("")
  const [settledSearch, setSettledSearch] = useState("")
  const [memberSelection, setMemberSelection] = useState<Set<string>>(new Set())
  const [availableSelection, setAvailableSelection] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const pageSize = 25

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setSettledSearch(availableSearch.trim())
      setAvailableOffset(0)
    }, 300)
    return () => window.clearTimeout(timeout)
  }, [availableSearch])

  const membersQuery = useQuery({
    queryKey: queryKeys.sourceCollectionSources(collection.id, memberOffset),
    queryFn: ({ signal }) => getSourceCollectionSources(collection.id, { limit: pageSize, offset: memberOffset }, signal),
    enabled: open,
  })
  const availableQuery = useQuery({
    queryKey: ["source-collections", collection.id, "available", availableOffset, settledSearch],
    queryFn: ({ signal }) => getSourcePage({
      excludeCollectionId: collection.id,
      search: settledSearch,
      limit: pageSize,
      offset: availableOffset,
    }, signal),
    enabled: open,
  })

  const members = membersQuery.data?.items ?? []
  const available = availableQuery.data?.items ?? []
  const currentCount = membersQuery.data?.total ?? collection.sourceCount
  const addMutation = useMutation({
    mutationFn: () => addSourcesToCollection(collection.id, [...availableSelection]),
    onSuccess: () => {
      setAvailableSelection(new Set())
      setError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCollectionSources(collection.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      onChanged()
    },
    onError: (requestError) => setError(getApiErrorMessage(requestError, "Could not add sources.")),
  })
  const removeMutation = useMutation({
    mutationFn: () => removeSourcesFromCollection(collection.id, [...memberSelection]),
    onSuccess: () => {
      setMemberSelection(new Set())
      setError(null)
      void queryClient.invalidateQueries({ queryKey: queryKeys.sourceCollectionSources(collection.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      onChanged()
    },
    onError: (requestError) => setError(getApiErrorMessage(requestError, "Could not remove sources.")),
  })

  const toggleSelection = (setter: Dispatch<SetStateAction<Set<string>>>, id: string) => {
    setter((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Manage sources · {collection.name}</DialogTitle>
          <DialogDescription>
            Add or remove sources in bulk. Membership updates are transactional and the collection cannot exceed 100 sources.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 lg:grid-cols-2">
          <MembershipList
            emptyMessage="No sources in this collection."
            loading={membersQuery.isPending}
            page={membersQuery.data}
            selected={memberSelection}
            sources={members}
            title={`Members · ${currentCount}/${collection.maximumSources}`}
            onPageChange={setMemberOffset}
            onToggle={(id) => toggleSelection(setMemberSelection, id)}
          />
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Available sources</h3>
              <Badge variant="neutral">Search is debounced</Badge>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input
                aria-label="Search available sources"
                className="pl-9"
                onChange={(event) => setAvailableSearch(event.target.value)}
                placeholder="Search by name, URL, or group"
                value={availableSearch}
              />
            </div>
            <SourceSelectionList
              emptyMessage="No matching sources outside this collection."
              loading={availableQuery.isPending}
              page={availableQuery.data}
              selected={availableSelection}
              sources={available}
              onPageChange={setAvailableOffset}
              onToggle={(id) => toggleSelection(setAvailableSelection, id)}
            />
            <Button
              className="w-full gap-1.5"
              disabled={addMutation.isPending || availableSelection.size === 0 || currentCount + availableSelection.size > collection.maximumSources}
              onClick={() => addMutation.mutate()}
              type="button"
            >
              {addMutation.isPending ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Plus className="size-4" aria-hidden="true" />}
              Add selected ({availableSelection.size})
            </Button>
            {currentCount + availableSelection.size > collection.maximumSources ? (
              <p className="text-xs text-destructive" role="alert">Select fewer sources; the collection limit is {collection.maximumSources}.</p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-3">
          <div className="min-w-0 text-sm text-muted-foreground">
            {error ? <span className="text-destructive" role="alert">{error}</span> : "Changes are applied immediately."}
          </div>
          <div className="flex gap-2">
            <Button
              className="gap-1.5"
              disabled={removeMutation.isPending || memberSelection.size === 0}
              onClick={() => removeMutation.mutate()}
              type="button"
              variant="destructive"
            >
              {removeMutation.isPending ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Trash2 className="size-4" aria-hidden="true" />}
              Remove selected ({memberSelection.size})
            </Button>
            <DialogClose render={<Button variant="outline" type="button">Done</Button>} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function MembershipList({
  emptyMessage,
  loading,
  page,
  selected,
  sources,
  title,
  onPageChange,
  onToggle,
}: {
  emptyMessage: string
  loading: boolean
  page: SourcePage | undefined
  selected: Set<string>
  sources: SourceSummary[]
  title: string
  onPageChange: (offset: number) => void
  onToggle: (id: string) => void
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <SourceSelectionList
        emptyMessage={emptyMessage}
        loading={loading}
        page={page}
        selected={selected}
        sources={sources}
        onPageChange={onPageChange}
        onToggle={onToggle}
      />
    </div>
  )
}

function SourceSelectionList({
  emptyMessage,
  loading,
  page,
  selected,
  sources,
  onPageChange,
  onToggle,
}: {
  emptyMessage: string
  loading: boolean
  page: SourcePage | undefined
  selected: Set<string>
  sources: SourceSummary[]
  onPageChange: (offset: number) => void
  onToggle: (id: string) => void
}) {
  const total = page?.total ?? 0
  const offset = page?.offset ?? 0
  const limit = page?.limit ?? 25
  return (
    <div className="overflow-hidden rounded-md border border-border/70">
      <div className="max-h-64 overflow-y-auto">
        {loading ? (
          <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground" role="status">
            <LoaderCircle className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            Loading sources
          </div>
        ) : sources.length ? (
          <div className="divide-y divide-border/60">
            {sources.map((source) => (
              <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5 transition-colors duration-150 hover:bg-muted/40" key={source.id}>
                <Checkbox
                  aria-label={`Select ${source.name}`}
                  checked={selected.has(source.id)}
                  onChange={() => onToggle(source.id)}
                />
                <SourceIcon
                  iconUrl={source.iconUrl}
                  iconUpdatedAt={source.iconUpdatedAt}
                  name={source.name}
                  platform={source.platform}
                  sourceId={source.id}
                />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{source.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">{source.category} · {source.platform}</span>
                </span>
              </label>
            ))}
          </div>
        ) : (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground">{emptyMessage}</p>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-border/60 px-2 py-1.5 text-xs text-muted-foreground">
        <span>{total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : "0 sources"}</span>
        <div className="flex gap-1">
          <Button
            aria-label="Previous source page"
            disabled={offset === 0 || loading}
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            size="icon-xs"
            type="button"
            variant="ghost"
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <Button
            aria-label="Next source page"
            disabled={!page?.hasMore || loading}
            onClick={() => onPageChange(offset + limit)}
            size="icon-xs"
            type="button"
            variant="ghost"
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </div>
  )
}

function newRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function isActiveContinuousStatus(status: string | null | undefined): boolean {
  return status === "starting" || status === "running" || status === "stopping"
}

function formatContinuousStatus(status: string): string {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
