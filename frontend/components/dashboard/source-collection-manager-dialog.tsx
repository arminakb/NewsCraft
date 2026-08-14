"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, LoaderCircle, Plus, Search, Trash2 } from "lucide-react"
import { useEffect, useState, type Dispatch, type SetStateAction } from "react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  addSourcesToCollection,
  getSourceCollectionSources,
  getSourcePage,
  removeSourcesFromCollection,
  type SourceCollectionSummary,
  type SourcePage,
} from "@/features/operations/ingestion-api"
import type { SourceSummary } from "@/features/operations/ingestion-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function CollectionManagerDialog({
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
    queryKey: queryKeys.sourceCollectionAvailableSources(collection.id, availableOffset, settledSearch),
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
