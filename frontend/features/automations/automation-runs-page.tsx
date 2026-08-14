"use client"

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { Activity, ExternalLink, FileText, Search, X } from "lucide-react"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useMemo, useRef } from "react"
import type React from "react"

import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { StatusBadge } from "@/components/ui/status-badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import { getAutomationRun, getAutomationRuns, getAutomations } from "./automation-api"
import { AutomationArea } from "./automation-area"
import { isTerminalRun, runTone } from "./automation-run-state"
import type { AutomationRun, AutomationRunFilters } from "./automation-types"

const AutomationRunDetail = dynamic(
  () => import("./automation-run-detail").then((module) => module.AutomationRunDetail),
  { ssr: false, loading: () => <LoadingState title="Loading run detail…" /> },
)

const statuses = ["pending", "queued", "running", "waiting_for_review", "succeeded", "warning", "failed", "cancelled"]

export function AutomationRunsPage() {
  const router = useRouter()
  const params = useSearchParams()
  const automationIdParam = params.get("automationId") ?? ""
  const runId = params.get("runId") ?? ""
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const detail = useQuery({
    queryKey: runId ? queryKeys.automationRun(runId) : ["automation-runs", "none"],
    queryFn: ({ signal }) => getAutomationRun(runId, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => query.state.data && !isTerminalRun(query.state.data.status) ? 2_000 : false,
    refetchIntervalInBackground: false,
  })
  const automationId = automationIdParam || detail.data?.automationId || ""
  const filters = useMemo<AutomationRunFilters>(() => ({
    limit: 25,
    status: params.get("status") || null,
    dryRun: params.get("mode") === "dry" ? true : params.get("mode") === "live" ? false : null,
    dateFrom: dayBoundary(params.get("from"), false),
    dateTo: dayBoundary(params.get("to"), true),
    failedOnly: params.get("failed") === "true",
  }), [params])
  const workflows = useQuery({ queryKey: queryKeys.automations({ limit: 100 }), queryFn: ({ signal }) => getAutomations({ limit: 100 }, signal) })
  const runs = useInfiniteQuery({
    queryKey: queryKeys.automationRuns(automationId, filters),
    queryFn: ({ pageParam, signal }) => getAutomationRuns(automationId, { ...filters, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: Boolean(automationId),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => query.state.data?.pages.some((page) => page.items.some((run) => !isTerminalRun(run.status))) ? 5_000 : false,
    refetchIntervalInBackground: false,
  })
  const items = runs.data?.pages.flatMap((page) => page.items) ?? []
  const workflowName = workflows.data?.items.find((item) => item.id === automationId)?.name ?? "Selected workflow"

  const updateUrl = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString())
    for (const [key, value] of Object.entries(updates)) value ? next.set(key, value) : next.delete(key)
    router.replace(`/automations/runs${next.size ? `?${next.toString()}` : ""}`, { scroll: false })
  }
  const inspect = (run: AutomationRun, trigger: HTMLButtonElement) => {
    triggerRef.current = trigger
    updateUrl({ runId: run.id, automationId: run.automationId })
  }
  const closeDetail = () => {
    updateUrl({ runId: null })
    window.setTimeout(() => triggerRef.current?.focus(), 0)
  }

  return (
    <AutomationArea title="Automation runs" description="Filter persisted workflow and node-run truth. Operational detail stays linked to Jobs.">
      <Card size="sm">
        <CardHeader className="border-b"><CardTitle>Run filters</CardTitle><CardDescription>Filters are deep-linked and applied by bounded backend queries.</CardDescription></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <Filter label="Workflow">
            <Select value={automationId} disabled={workflows.isPending || workflows.isError} onChange={(event) => updateUrl({ automationId: event.target.value || null, runId: null })}>
              <option value="">Choose workflow</option>
              {workflows.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </Select>
          </Filter>
          <Filter label="State">
            <Select value={params.get("status") ?? ""} onChange={(event) => updateUrl({ status: event.target.value || null })}>
              <option value="">All states</option>
              {statuses.map((status) => <option key={status} value={status}>{humanize(status)}</option>)}
            </Select>
          </Filter>
          <Filter label="Mode">
            <Select value={params.get("mode") ?? ""} onChange={(event) => updateUrl({ mode: event.target.value || null })}>
              <option value="">Dry and live</option><option value="dry">Dry run</option><option value="live">Live</option>
            </Select>
          </Filter>
          <Filter label="From"><Input type="date" value={params.get("from") ?? ""} onChange={(event) => updateUrl({ from: event.target.value || null })} /></Filter>
          <Filter label="To"><Input type="date" value={params.get("to") ?? ""} onChange={(event) => updateUrl({ to: event.target.value || null })} /></Filter>
          <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm font-medium sm:col-span-2 xl:col-span-5">
            <Checkbox checked={params.get("failed") === "true"} onChange={(event) => updateUrl({ failed: event.target.checked ? "true" : null })} />
            Failed only
          </label>
          {workflows.isError ? <p className="text-sm text-destructive sm:col-span-2 xl:col-span-5" role="alert">{getApiErrorMessage(workflows.error)}</p> : null}
        </CardContent>
      </Card>

      {!automationId ? <EmptyState icon={Activity} title="Choose workflow" description="Runs stay grouped by durable workflow and immutable version." /> : null}
      {runs.isPending && automationId ? <LoadingState title="Loading runs…" /> : null}
      {runs.isError ? <ErrorState title="Runs unavailable" description={getApiErrorMessage(runs.error)} action={<Button variant="outline" onClick={() => void runs.refetch()}>Retry runs</Button>} /> : null}
      {runs.data && !items.length ? <EmptyState icon={Search} title="No runs match filters" description="Change filters or start dry run from workflow editor." /> : null}
      {items.length ? (
        <Card size="sm">
          <CardHeader className="border-b"><CardTitle>{workflowName}</CardTitle><CardDescription>{items.length} persisted run{items.length === 1 ? "" : "s"} loaded.</CardDescription></CardHeader>
          <CardContent className="px-0">
            <div className="hidden sm:block">
              <Table aria-label="Automation runs">
                <TableHeader><TableRow><TableHead>Version / trigger</TableHead><TableHead>Started / duration</TableHead><TableHead>Current stage</TableHead><TableHead>Outcome / mode</TableHead><TableHead>Draft / Job / Publication</TableHead><TableHead><span className="sr-only">Actions</span></TableHead></TableRow></TableHeader>
                <TableBody>{items.map((run) => <RunRow key={run.id} run={run} onInspect={inspect} />)}</TableBody>
              </Table>
            </div>
            <div className="flex flex-col gap-3 px-3 sm:hidden" aria-label="Automation runs mobile list">
              {items.map((run) => <RunCard key={run.id} run={run} onInspect={inspect} />)}
            </div>
          </CardContent>
        </Card>
      ) : null}
      {runs.hasNextPage ? <Button variant="outline" disabled={runs.isFetchingNextPage} onClick={() => void runs.fetchNextPage()}>{runs.isFetchingNextPage ? "Loading…" : "Load older runs"}</Button> : null}

      <Sheet open={Boolean(runId)} onOpenChange={(open) => { if (!open) closeDetail() }}>
        <SheetContent side="right" className="max-w-2xl" initialFocus={closeRef}>
          <div className="h-full overflow-y-auto p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            <SheetHeader className="pr-12"><SheetTitle>Run detail</SheetTitle><SheetDescription>Persisted node results, exact revision, and related Job links.</SheetDescription></SheetHeader>
            <SheetClose ref={closeRef} aria-label="Close run detail" className="absolute right-3 top-3 grid size-11 place-items-center rounded-lg hover:bg-navigation-hover"><X aria-hidden="true" /></SheetClose>
            <div className="mt-5">
              {detail.isPending ? <LoadingState title="Loading run detail…" /> : null}
              {detail.isError ? <ErrorState title="Run unavailable" description={getApiErrorMessage(detail.error)} action={<Button variant="outline" onClick={() => void detail.refetch()}>Retry run</Button>} /> : null}
              {detail.data ? <AutomationRunDetail run={detail.data} /> : null}
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </AutomationArea>
  )
}

function RunRow({ run, onInspect }: { run: AutomationRun; onInspect: (run: AutomationRun, trigger: HTMLButtonElement) => void }) {
  const revision = revisionId(run)
  const job = run.rootWorkflowJobId
  return (
    <TableRow>
      <TableCell><p className="font-medium">Version {version(run)}</p><p className="text-xs text-muted-foreground">{humanize(run.triggerKind)}</p></TableCell>
      <TableCell><p>{new Date(run.startedAt ?? run.createdAt).toLocaleString()}</p><p className="text-xs text-muted-foreground">{duration(run)}</p></TableCell>
      <TableCell>{run.currentNodeId ? humanize(run.currentNodeId) : "Complete"}</TableCell>
      <TableCell><StatusBadge tone={runTone(run.status)}>{humanize(run.status)}</StatusBadge><p className="mt-1 text-xs text-muted-foreground">{run.dryRun ? "Dry run" : "Live"}</p></TableCell>
      <TableCell className="whitespace-normal"><RunLinks run={run} revision={revision} job={job} /></TableCell>
      <TableCell><Button variant="outline" size="sm" onClick={(event) => onInspect(run, event.currentTarget)}>Inspect</Button></TableCell>
    </TableRow>
  )
}

function RunCard({ run, onInspect }: { run: AutomationRun; onInspect: (run: AutomationRun, trigger: HTMLButtonElement) => void }) {
  return (
    <Card size="sm">
      <CardHeader><div className="flex items-center justify-between gap-2"><CardTitle>Version {version(run)}</CardTitle><StatusBadge tone={runTone(run.status)}>{humanize(run.status)}</StatusBadge></div><CardDescription>{humanize(run.triggerKind)} · {run.dryRun ? "Dry run" : "Live"}</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-3"><p className="text-sm">{new Date(run.startedAt ?? run.createdAt).toLocaleString()} · {duration(run)}</p><p className="text-sm">Stage: {run.currentNodeId ? humanize(run.currentNodeId) : "Complete"}</p><RunLinks run={run} revision={revisionId(run)} job={run.rootWorkflowJobId} /><Button variant="outline" onClick={(event) => onInspect(run, event.currentTarget)}>Inspect run</Button></CardContent>
    </Card>
  )
}

function RunLinks({ run, revision, job }: { run: AutomationRun; revision: string | null; job: string | null }) {
  const publication = run.nodes.find((node) => node.publicationId)?.publicationId
  return <div className="flex flex-wrap gap-2">{revision ? <Link className={buttonVariants({ variant: "ghost", size: "sm" })} href={`/review/${revision}`}><FileText data-icon="inline-start" aria-hidden="true" />Revision</Link> : null}{job ? <Link className={buttonVariants({ variant: "ghost", size: "sm" })} href={`/operations?view=jobs&job=${job}`}><ExternalLink data-icon="inline-start" aria-hidden="true" />Job</Link> : null}{publication ? <span className="self-center text-xs text-muted-foreground">Publication {publication.slice(0, 8)}</span> : null}{!revision && !job && !publication ? <span className="text-xs text-muted-foreground">No artifact yet</span> : null}</div>
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1.5 text-[13px] font-medium"><span>{label}</span>{children}</label>
}

function version(run: AutomationRun) {
  const value = run.resourceSnapshot.automationVersion
  return typeof value === "string" || typeof value === "number" ? value : run.automationVersionId.slice(0, 8)
}

function revisionId(run: AutomationRun) {
  return run.nodes.find((node) => node.platformVariantRevisionId)?.platformVariantRevisionId ?? null
}

function duration(run: AutomationRun) {
  if (!run.startedAt || !run.finishedAt) return run.startedAt ? "In progress" : "Not started"
  const milliseconds = Math.max(0, new Date(run.finishedAt).getTime() - new Date(run.startedAt).getTime())
  return milliseconds < 60_000 ? `${(milliseconds / 1_000).toFixed(1)} s` : `${Math.floor(milliseconds / 60_000)}m ${Math.floor((milliseconds % 60_000) / 1_000)}s`
}

function dayBoundary(value: string | null, end: boolean) {
  return value ? `${value}T${end ? "23:59:59.999" : "00:00:00.000"}Z` : null
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
