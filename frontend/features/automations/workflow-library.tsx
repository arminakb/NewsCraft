"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  CheckCircle2,
  CirclePause,
  Clock3,
  Copy,
  MoreHorizontal,
  Play,
  Plus,
  Search,
  TestTube2,
  Trash2,
  Workflow,
  X,
} from "lucide-react"
import { useRouter } from "next/navigation"
import { type FormEvent, useMemo, useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
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
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/menu"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { Select } from "@/components/ui/select"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import {
  activateAutomation,
  archiveAutomation,
  duplicateAutomation,
  getAutomations,
  pauseAutomation,
  resumeAutomation,
} from "./automation-api"
import { AutomationArea } from "./automation-area"
import type { Automation, AutomationPlatform } from "./automation-types"
import { WorkflowMiniPreview, workflowStageLabel } from "./workflow-mini-preview"
import { platformLabel, primaryPlatform, WorkflowPlatformIcon } from "./workflow-platform-icon"

export function WorkflowLibrary() {
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("")
  const [trigger, setTrigger] = useState("")
  const [platform, setPlatform] = useState("")
  const [sort, setSort] = useState<"updated" | "name">("updated")
  const workflows = useQuery({
    queryKey: queryKeys.automations({ limit: 50 }),
    queryFn: ({ signal }) => getAutomations({ limit: 50 }, signal),
  })
  const items = workflows.data?.items ?? []
  const visibleItems = useMemo(
    () => filterAndSortWorkflows(items, { search, status, trigger, platform, sort }),
    [items, platform, search, sort, status, trigger],
  )
  const filterOptions = useMemo(() => workflowFilterOptions(items), [items])
  const filtered = Boolean(search.trim() || status || trigger || platform)
  const clearFilters = () => {
    setSearch("")
    setStatus("")
    setTrigger("")
    setPlatform("")
  }

  return (
    <AutomationArea title="Automations" showHeader={false}>
      {workflows.isPending ? <LoadingState title="Loading workflows…" /> : null}
      {workflows.isError ? (
        <ErrorState
          title="Workflow library unavailable"
          description={getApiErrorMessage(workflows.error)}
          action={<Button variant="outline" onClick={() => void workflows.refetch()}>Retry workflows</Button>}
        />
      ) : null}
      {workflows.data ? (
        <section aria-labelledby="workflow-library-heading" className="min-w-0">
          <h2 className="sr-only" id="workflow-library-heading">Workflow library</h2>
          {workflows.data.items.length ? (
            <WorkflowLibraryFilters
              filters={{ search, status, trigger, platform, sort }}
              options={filterOptions}
              onSearch={setSearch}
              onStatus={setStatus}
              onTrigger={setTrigger}
              onPlatform={setPlatform}
              onSort={setSort}
              onClear={clearFilters}
            />
          ) : null}
          <p aria-live="polite" className="sr-only" role="status">
            {workflows.data.items.length ? `${visibleItems.length} ${visibleItems.length === 1 ? "workflow" : "workflows"} shown.` : ""}
          </p>
          {!workflows.data.items.length ? (
            <EmptyState
              className="mb-2 min-h-28"
              icon={Workflow}
              title="No workflows yet"
              description="Create your first versioned newsroom workflow."
            />
          ) : null}
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 min-[1360px]:grid-cols-4" aria-label="Workflow cards">
            {filtered && !visibleItems.length ? (
              <EmptyState
                className="min-h-[214px] rounded-xl border border-dashed"
                icon={Search}
                title="No workflows match"
                description="Try another name, stage, trigger, status, or platform."
                action={<Button variant="outline" onClick={clearFilters}>Clear filters</Button>}
              />
            ) : null}
            {visibleItems.map((automation) => <WorkflowCard automation={automation} key={automation.id} />)}
            <CreateWorkflowCard />
          </div>
        </section>
      ) : null}
    </AutomationArea>
  )
}

type WorkflowFilters = {
  search: string
  status: string
  trigger: string
  platform: string
  sort: "updated" | "name"
}

function WorkflowLibraryFilters({
  filters,
  options,
  onSearch,
  onStatus,
  onTrigger,
  onPlatform,
  onSort,
  onClear,
}: {
  filters: WorkflowFilters
  options: ReturnType<typeof workflowFilterOptions>
  onSearch: (value: string) => void
  onStatus: (value: string) => void
  onTrigger: (value: string) => void
  onPlatform: (value: string) => void
  onSort: (value: WorkflowFilters["sort"]) => void
  onClear: () => void
}) {
  const filtered = Boolean(filters.search || filters.status || filters.trigger || filters.platform)
  return (
    <div className="mb-3 grid min-w-0 grid-cols-2 gap-2 rounded-xl border border-border/60 bg-card p-2 shadow-xs lg:flex lg:items-center" aria-label="Workflow filters" role="search">
      <label className="col-span-2 min-w-0 lg:w-64 xl:w-72">
        <span className="sr-only">Search workflows</span>
        <span className="flex min-h-11 items-center gap-2 rounded-lg border border-input bg-background px-3 transition-[border-color,box-shadow] duration-150 has-[:focus-visible]:border-ring has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/30 lg:min-h-9">
          <Search aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <input
            aria-label="Search workflows"
            className="min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden lg:text-[13px]"
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Search workflows..."
            type="search"
            value={filters.search}
          />
          {filters.search ? (
            <button
              aria-label="Clear workflow search"
              className="grid size-7 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => onSearch("")}
              type="button"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          ) : null}
        </span>
      </label>
      <Select aria-label="Filter workflows by status" className="lg:w-32" onChange={(event) => onStatus(event.target.value)} value={filters.status}>
        <option value="">All statuses</option>
        {options.statuses.map((item) => <option key={item} value={item}>{workflowLifecycleLabel(item as Automation["lifecycle"])}</option>)}
      </Select>
      <Select aria-label="Filter workflows by trigger" className="lg:w-36" onChange={(event) => onTrigger(event.target.value)} value={filters.trigger}>
        <option value="">All triggers</option>
        {options.triggers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </Select>
      <Select aria-label="Filter workflows by platform" className="lg:w-36" onChange={(event) => onPlatform(event.target.value)} value={filters.platform}>
        <option value="">All platforms</option>
        {options.platforms.map((item) => <option key={item} value={item}>{platformLabel([item])}</option>)}
      </Select>
      <Select aria-label="Sort workflows" className="lg:ms-auto lg:w-36" onChange={(event) => onSort(event.target.value as WorkflowFilters["sort"])} value={filters.sort}>
        <option value="updated">Last updated</option>
        <option value="name">Name A–Z</option>
      </Select>
      {filtered ? (
        <Button aria-label="Clear all workflow filters" className="col-span-2 lg:shrink-0" onClick={onClear} size="sm" variant="ghost">
          <X aria-hidden="true" />Clear
        </Button>
      ) : null}
    </div>
  )
}

function WorkflowCard({ automation }: { automation: Automation }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["automations"] }),
      queryClient.invalidateQueries({ queryKey: queryKeys.automation(automation.id) }),
    ])
  }
  const transition = useMutation({
    mutationFn: async (action: "activate" | "pause" | "resume") => {
      setActionError(null)
      if (action === "activate") return activateAutomation(automation.id, automation.revision, key("activate"))
      if (action === "pause") return pauseAutomation(automation.id, automation.revision)
      return resumeAutomation(automation.id, automation.revision)
    },
    onSuccess: invalidate,
    onError: (error) => setActionError(getApiErrorMessage(error)),
  })
  const duplicate = useMutation({
    mutationFn: () => duplicateAutomation(automation.id, { name: `Copy of ${automation.name}` }, key("duplicate")),
    onSuccess: async (copy) => { await invalidate(); router.push(`/automations/${copy.id}`) },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  })
  const deleteWorkflow = useMutation({
    mutationFn: () => archiveAutomation(automation.id, automation.revision),
    onSuccess: async () => { setDeleteOpen(false); await invalidate() },
    onError: (error) => setActionError(getApiErrorMessage(error)),
  })
  const pending = transition.isPending || duplicate.isPending || deleteWorkflow.isPending
  const preview = automation.preview
  const platforms = preview?.outputPlatforms ?? ["unknown"]
  const endpoints = workflowEndpoints(preview)

  return (
    <Card
      aria-labelledby={`workflow-${automation.id}`}
      className={`group/workflow relative isolate min-h-[214px] min-w-0 gap-0 py-0 transition-[border-color,box-shadow,background-color] duration-200 hover:bg-interactive motion-reduce:transition-none ${workflowCardStateClass(automation.lifecycle)}`}
      data-workflow-card
      data-workflow-status={automation.lifecycle}
      size="sm"
    >
      <button
        aria-label={`Open workflow: ${automation.name}`}
        className="absolute inset-0 z-10 cursor-pointer rounded-xl transition-colors duration-150 active:bg-navigation-active/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring motion-reduce:transition-none"
        onClick={() => router.push(`/automations/${automation.id}`)}
        type="button"
      />
      <CardHeader className="relative px-3 pb-2 pt-3">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <CardTitle className="min-w-0 flex-1 truncate text-[15px] font-semibold" id={`workflow-${automation.id}`} title={automation.name}>
                {automation.name}
              </CardTitle>
              <span
                aria-label={`Output platform: ${platformLabel(platforms)}`}
                className={`grid size-7 shrink-0 place-items-center rounded-lg border ${platformIdentityClass(primaryPlatform(platforms))}`}
                role="img"
                title={`Output platform: ${platformLabel(platforms)}`}
              >
                <WorkflowPlatformIcon className="size-5" platform={primaryPlatform(platforms)} />
              </span>
            </div>
            {endpoints ? (
              <p
                className="mt-1 flex min-w-0 items-center text-xs text-muted-foreground"
                data-workflow-endpoints
                title={`${endpoints.start} → ${endpoints.end}`}
              >
                <span className="sr-only">{endpoints.start} to {endpoints.end}</span>
                <span aria-hidden="true" className="truncate">{endpoints.start}</span>
                <span
                  aria-hidden="true"
                  className="mx-0.5 block size-3 shrink-0 bg-foreground"
                  data-workflow-arrow
                  style={{
                    WebkitMask: "url('/icons/right-arrow-svgrepo-com.svg') center / contain no-repeat",
                    mask: "url('/icons/right-arrow-svgrepo-com.svg') center / contain no-repeat",
                  }}
                />
                <span aria-hidden="true" className="truncate">{endpoints.end}</span>
              </p>
            ) : null}
            <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="text-xs tabular-nums text-muted-foreground">
                {preview ? `${preview.versionState === "active" ? "v" : "Draft v"}${preview.version}` : "Version unavailable"}
              </span>
              {automation.lifecycle !== "inactive" ? (
                <>
                  <span aria-hidden="true" className="text-border">·</span>
                  <StatusBadge className="h-5 px-1.5 text-xs" tone={lifecycleTone(automation.lifecycle)}>{workflowLifecycleLabel(automation.lifecycle)}</StatusBadge>
                </>
              ) : null}
            </div>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label={`More actions for ${automation.name}`}
              className={`${buttonVariants({ variant: "ghost", size: "icon" })} relative z-20 -me-2 -mt-2 min-h-11 min-w-11`}
              disabled={pending}
            >
              <MoreHorizontal aria-hidden="true" />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => router.push(`/automations/${automation.id}#test-studio`)}><TestTube2 aria-hidden="true" className="size-4" />Test workflow</DropdownMenuItem>
              <DropdownMenuItem onClick={() => duplicate.mutate()}><Copy aria-hidden="true" className="size-4" />Duplicate</DropdownMenuItem>
              <DropdownMenuItem onClick={() => transition.mutate(automation.lifecycle === "active" ? "pause" : automation.lifecycle === "paused" ? "resume" : "activate")}>
                {automation.lifecycle === "active" ? <CirclePause aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
                {automation.lifecycle === "active" ? "Pause" : automation.lifecycle === "paused" ? "Resume" : "Activate"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive disabled={automation.lifecycle === "active"} onClick={() => setDeleteOpen(true)}><Trash2 aria-hidden="true" className="size-4" />Delete</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col justify-center px-3 py-1">
        <WorkflowMiniPreview stages={preview?.stages ?? []} paused={automation.lifecycle !== "active"} />
      </CardContent>
      {actionError ? <Alert className="relative z-20 mx-3 mb-2" tone="error" role="alert"><AlertDescription>{actionError}</AlertDescription></Alert> : null}
      <WorkflowCardFooter automation={automation} />
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete workflow?</DialogTitle>
            <DialogDescription>
              Delete {automation.name}? This removes it from the active library using the existing workflow deletion action. Active workflows must be paused first.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose className={buttonVariants({ variant: "outline" })}>No</DialogClose>
            <Button variant="destructive" disabled={deleteWorkflow.isPending} onClick={() => deleteWorkflow.mutate()}>{deleteWorkflow.isPending ? "Deleting…" : "Yes, delete workflow"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function WorkflowCardFooter({ automation }: { automation: Automation }) {
  const preview = automation.preview
  if (!preview?.runCount) {
    return <CardFooter className="min-h-9 justify-start border-border/40 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">Not run yet</CardFooter>
  }
  return (
    <CardFooter className="min-h-9 justify-between gap-2 border-border/40 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
      <span className="inline-flex min-w-0 items-center gap-1">
        <Clock3 aria-hidden="true" className="size-3.5 shrink-0" />
        <time dateTime={preview.lastRunAt ?? undefined} suppressHydrationWarning>{formatRelativeTime(preview.lastRunAt)}</time>
      </span>
      <span className="shrink-0 tabular-nums">{preview.runCount} {preview.runCount === 1 ? "run" : "runs"}</span>
      {preview.successRate === null ? (
        <span className="min-w-0 truncate text-end" title={`Last outcome: ${label(preview.lastOutcome ?? "unknown")}`}>
          {label(preview.lastOutcome ?? "Unknown")}
        </span>
      ) : (
        <span aria-label={`Success rate: ${preview.successRate}%`} className="inline-flex shrink-0 items-center gap-1 font-medium tabular-nums text-success" role="img">
          <CheckCircle2 aria-hidden="true" className="size-3.5" />
          <span aria-hidden="true">{preview.successRate}%</span>
        </span>
      )}
    </CardFooter>
  )
}

function CreateWorkflowCard() {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [nameTouched, setNameTouched] = useState(false)
  const trimmedName = name.trim()
  const nameError = nameTouched && !trimmedName ? "Enter a workflow name." : null

  const onOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (!nextOpen) {
      setName("")
      setNameTouched(false)
    }
  }

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setNameTouched(true)
    if (!trimmedName) return
    onOpenChange(false)
    router.push(`/automations/new?name=${encodeURIComponent(trimmedName)}`)
  }

  return (
    <>
      <button
        aria-label="Create new workflow"
        className="group/create flex min-h-[214px] min-w-0 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-primary/35 bg-card px-5 py-6 text-center shadow-xs transition-[border-color,background-color,box-shadow] duration-200 hover:border-primary/60 hover:bg-accent/35 hover:shadow-sm active:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
        onClick={() => setOpen(true)}
        type="button"
      >
        <span className="grid size-8 place-items-center rounded-full border border-primary/45 bg-accent text-accent-foreground transition-colors duration-200 group-hover/create:bg-primary-solid group-hover/create:text-primary-solid-foreground motion-reduce:transition-none">
          <Plus aria-hidden="true" className="size-4" />
        </span>
        <span className="mt-3 font-semibold text-foreground">Create New Workflow</span>
        <span className="mt-1 max-w-56 text-sm text-muted-foreground">Open the guided workflow creator</span>
      </button>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <form className="space-y-5" onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>Name your workflow</DialogTitle>
              <DialogDescription>Choose a name for your blank workflow before opening the editor.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-1.5">
              <label className="text-sm font-medium" htmlFor="new-workflow-name">Workflow name</label>
              <Input
                aria-describedby={nameError ? "new-workflow-name-error" : undefined}
                aria-invalid={Boolean(nameError)}
                aria-required="true"
                autoFocus
                id="new-workflow-name"
                onBlur={() => setNameTouched(true)}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Morning newsroom"
                value={name}
              />
              {nameError ? <p className="text-xs text-destructive" id="new-workflow-name-error" role="alert">{nameError}</p> : null}
            </div>
            <DialogFooter>
              <DialogClose className={buttonVariants({ variant: "outline" })}>Cancel</DialogClose>
              <Button type="submit">Create workflow</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

function lifecycleTone(value: Automation["lifecycle"]): StatusTone {
  if (value === "active") return "success"
  if (value === "paused") return "warning"
  if (value === "archived") return "neutral"
  return "info"
}

function workflowCardStateClass(value: Automation["lifecycle"]) {
  if (value === "active") {
    return "border-success/40 shadow-[0_0_24px_color-mix(in_srgb,var(--success),transparent_78%)] hover:border-success/60 hover:shadow-[0_0_30px_color-mix(in_srgb,var(--success),transparent_70%)]"
  }
  if (value === "paused") {
    return "border-warning/40 shadow-[0_0_24px_color-mix(in_srgb,var(--warning),transparent_78%)] hover:border-warning/60 hover:shadow-[0_0_30px_color-mix(in_srgb,var(--warning),transparent_70%)]"
  }
  return "shadow-xs hover:border-foreground/20 hover:shadow-sm"
}

function workflowEndpoints(preview: Automation["preview"]) {
  if (!preview?.stages.length) return null
  return {
    start: workflowStageLabel(preview.stages[0]),
    end: platformLabel(preview.outputPlatforms),
  }
}

function workflowLifecycleLabel(value: Automation["lifecycle"]) {
  return value === "inactive" ? "Draft" : label(value)
}

function platformIdentityClass(platform: AutomationPlatform) {
  if (platform === "telegram") return "border-[var(--flow-telegram-border)] bg-[var(--flow-telegram-surface)] text-[var(--flow-telegram)] shadow-[0_0_16px_color-mix(in_srgb,var(--flow-telegram),transparent_85%)]"
  if (platform === "x") return "border-[var(--flow-x-border)] bg-[var(--flow-x-surface)] text-[var(--flow-x)]"
  if (platform === "blog") return "border-[var(--flow-blog-border)] bg-[var(--flow-blog-surface)] text-[var(--flow-blog)]"
  if (platform === "draft") return "border-[var(--flow-draft-border)] bg-[var(--flow-draft-surface)] text-[var(--flow-draft)]"
  if (platform === "multi") return "border-primary/35 bg-accent text-accent-foreground"
  return "border-border bg-muted text-muted-foreground"
}

function filterAndSortWorkflows(items: Automation[], filters: WorkflowFilters) {
  const query = normalize(filters.search)
  return items
    .filter((automation) => {
      const preview = automation.preview
      const stages = preview?.stages ?? []
      const searchable = normalize([
        automation.name,
        platformLabel(preview?.outputPlatforms ?? ["unknown"]),
        ...stages.flatMap((stage) => [stage.label, workflowStageLabel(stage), stage.nodeType]),
      ].join(" "))
      return (!query || searchable.includes(query))
        && (!filters.status || automation.lifecycle === filters.status)
        && (!filters.trigger || stages[0]?.nodeType === filters.trigger)
        && (!filters.platform || preview?.outputPlatforms.includes(filters.platform as AutomationPlatform))
    })
    .sort((left, right) => filters.sort === "name"
      ? left.name.localeCompare(right.name, undefined, { sensitivity: "base" })
      : Date.parse(right.updatedAt) - Date.parse(left.updatedAt))
}

function workflowFilterOptions(items: Automation[]) {
  const statuses = [...new Set(items.map((item) => item.lifecycle))]
  const triggers = [...new Map(items.flatMap((item) => {
    const stage = item.preview?.stages[0]
    return stage ? [[stage.nodeType, { value: stage.nodeType, label: workflowStageLabel(stage) }]] as const : []
  })).values()].sort((left, right) => left.label.localeCompare(right.label))
  const platforms = [...new Set(items.flatMap((item) => item.preview?.outputPlatforms ?? []))]
    .sort((left, right) => platformLabel([left]).localeCompare(platformLabel([right])))
  return { statuses, triggers, platforms }
}

function normalize(value: string) {
  return value.normalize("NFKD").toLocaleLowerCase().trim()
}

function formatRelativeTime(value: string | null) {
  if (!value) return "Run time unavailable"
  const time = Date.parse(value)
  if (!Number.isFinite(time)) return "Run time unavailable"
  const seconds = Math.round((time - Date.now()) / 1_000)
  const absolute = Math.abs(seconds)
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
  if (absolute < 60) return formatter.format(seconds, "second")
  if (absolute < 3_600) return formatter.format(Math.round(seconds / 60), "minute")
  if (absolute < 86_400) return formatter.format(Math.round(seconds / 3_600), "hour")
  return formatter.format(Math.round(seconds / 86_400), "day")
}

function label(value: string) {
  return value.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ")
}

function key(action: string) {
  return `workflow-${action}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`
}
