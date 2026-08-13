"use client"

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { GitCompareArrows, History, LoaderCircle, RotateCcw, X } from "lucide-react"
import { useMemo, useRef, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { StatusBadge } from "@/components/ui/status-badge"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import { getAutomationRuns, getAutomationVersions, restoreAutomationVersion } from "./automation-api"
import type { AutomationVersion } from "./automation-types"

export default function AutomationVersionHistory({
  open,
  onOpenChange,
  automationId,
  activeVersionId,
  draftVersionId,
  currentVersion,
  expectedRevision,
  onRestored,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  automationId: string
  activeVersionId: string | null
  draftVersionId: string | null
  currentVersion: AutomationVersion
  expectedRevision: number
  onRestored: (version: AutomationVersion) => void
}) {
  const queryClient = useQueryClient()
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const [compare, setCompare] = useState<AutomationVersion | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const versions = useInfiniteQuery({
    queryKey: queryKeys.automationVersions(automationId),
    queryFn: ({ pageParam, signal }) => getAutomationVersions(automationId, { limit: 20, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
  })
  const runs = useQuery({
    queryKey: queryKeys.automationRuns(automationId, { limit: 100 }),
    queryFn: ({ signal }) => getAutomationRuns(automationId, { limit: 100 }, signal),
  })
  const pinned = useMemo(() => new Set(runs.data?.items.map((run) => run.automationVersionId) ?? []), [runs.data])
  const restore = useMutation({
    mutationFn: (version: number) => restoreAutomationVersion(automationId, version, expectedRevision, idempotencyKey(version)),
    onSuccess: async (version) => {
      onRestored(version)
      setMessage(`Version ${version.version} created as new editable draft. History stayed immutable.`)
      await queryClient.invalidateQueries({ queryKey: queryKeys.automationVersions(automationId) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.automation(automationId) })
    },
    onError: (error) => setMessage(getApiErrorMessage(error)),
  })
  const items = versions.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="max-w-2xl" initialFocus={closeRef}>
        <div className="h-full overflow-y-auto p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
          <SheetHeader className="pr-12">
            <SheetTitle>Immutable version history</SheetTitle>
            <SheetDescription>Inspect safe structural diffs. Restore always creates new draft; historical versions never change.</SheetDescription>
          </SheetHeader>
          <SheetClose ref={closeRef} aria-label="Close version history" className="absolute right-3 top-3 grid size-11 place-items-center rounded-lg hover:bg-navigation-hover"><X aria-hidden="true" /></SheetClose>

          <div className="mt-5 flex flex-col gap-4">
            {message ? <Alert tone={restore.isError ? "error" : "success"} role={restore.isError ? "alert" : "status"}><div><AlertTitle>{restore.isError ? "Restore failed" : "Draft restored"}</AlertTitle><AlertDescription>{message}</AlertDescription></div></Alert> : null}
            {compare ? (
              <Card size="sm">
                <CardHeader><CardTitle>Version {compare.version} compared with version {currentVersion.version}</CardTitle><CardDescription>Config values stay hidden; only structural change counts appear.</CardDescription></CardHeader>
                <CardContent><VersionDiff older={compare} current={currentVersion} /></CardContent>
              </Card>
            ) : null}
            {versions.isPending ? <p className="text-sm text-muted-foreground" role="status">Loading versions…</p> : null}
            {versions.isError ? <p className="text-sm text-destructive" role="alert">{getApiErrorMessage(versions.error)}</p> : null}
            <div className="flex flex-col gap-3" aria-label="Workflow versions">
              {items.map((version) => {
                const current = version.id === currentVersion.id
                return (
                  <Card size="sm" key={version.id}>
                    <CardHeader>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <CardTitle>Version {version.version}</CardTitle>
                        <div className="flex flex-wrap gap-1.5">
                          {version.id === activeVersionId ? <StatusBadge tone="success">Active</StatusBadge> : null}
                          {version.id === draftVersionId ? <StatusBadge tone="info">Draft</StatusBadge> : null}
                          {pinned.has(version.id) ? <StatusBadge tone="warning">Run pinned</StatusBadge> : null}
                          {current ? <StatusBadge tone="neutral">Open</StatusBadge> : null}
                        </div>
                      </div>
                      <CardDescription>{version.creationReason} · {new Date(version.createdAt).toLocaleString()}</CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" onClick={() => setCompare(version)}><GitCompareArrows data-icon="inline-start" aria-hidden="true" />Compare structure</Button>
                      {!current ? <Button size="sm" disabled={restore.isPending} onClick={() => restore.mutate(version.version)}>{restore.isPending ? <LoaderCircle data-icon="inline-start" className="animate-spin" aria-hidden="true" /> : <RotateCcw data-icon="inline-start" aria-hidden="true" />}Restore as new draft</Button> : null}
                    </CardContent>
                  </Card>
                )
              })}
            </div>
            {versions.hasNextPage ? <Button variant="outline" disabled={versions.isFetchingNextPage} onClick={() => void versions.fetchNextPage()}><History data-icon="inline-start" aria-hidden="true" />{versions.isFetchingNextPage ? "Loading…" : "Load older versions"}</Button> : null}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function VersionDiff({ older, current }: { older: AutomationVersion; current: AutomationVersion }) {
  const oldNodes = new Map(older.graph.nodes.map((node) => [node.id, node]))
  const currentNodes = new Map(current.graph.nodes.map((node) => [node.id, node]))
  const added = [...currentNodes.keys()].filter((id) => !oldNodes.has(id)).length
  const removed = [...oldNodes.keys()].filter((id) => !currentNodes.has(id)).length
  const changed = [...currentNodes].filter(([id, node]) => {
    const previous = oldNodes.get(id)
    return previous && (previous.type !== node.type || JSON.stringify(previous.config) !== JSON.stringify(node.config))
  }).length
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-4">
      <Metric label="Steps added" value={added} />
      <Metric label="Steps removed" value={removed} />
      <Metric label="Configs changed" value={changed} />
      <Metric label="Edge delta" value={current.graph.edges.length - older.graph.edges.length} />
    </dl>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-semibold tabular-nums">{value > 0 ? `+${value}` : value}</dd></div>
}

function idempotencyKey(version: number) {
  return `workflow-restore-${version}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`
}
