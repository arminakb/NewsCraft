"use client"

import { keepPreviousData, useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query"
import {
  Activity,
  CheckCircle2,
  Clipboard,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { useDateTime } from "@/components/providers/date-time-provider"
import { useNotices } from "@/components/providers/notice-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { cancelJob, getJob, getJobs, getJobSummary, retryJob } from "@/features/jobs/api"
import { JobDetailPanel } from "@/features/jobs/job-detail-panel"
import { JobTable } from "@/features/jobs/job-table"
import type { JobStatus, WorkflowJob } from "@/features/jobs/types"
import { getApiErrorMessage } from "@/lib/http"
import { formatInTimeZone } from "@/lib/date-time"
import { operationsQueryKeys, queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"

import { fetchOperationalHealth, fetchOperationsDiagnostics } from "./api"
import type {
  OperationalComponent,
  OperationalDependency,
  OperationalHealthSnapshot,
  OperationalHealthState,
  OperationalQueue,
  OperationsSnapshot,
} from "./types"

type OperationsView = "overview" | "jobs" | "diagnostics"
type DateRange = "all" | "24h" | "7d" | "30d"
type IssueSeverity = "error" | "warning"

type OperationsQuery = {
  view?: string | null
  status?: string | null
  job?: string | null
  type?: string | null
  range?: string | null
  search?: string | null
  failed?: string | null
}

type Issue = {
  key: string
  title: string
  component: string
  severity: IssueSeverity
  occurredAt: string
  actionHref?: string
  actionLabel?: string
  code?: string
  explanation?: string
}

const viewLabels: Array<{ value: OperationsView; label: string }> = [
  { value: "overview", label: "Overview" },
  { value: "jobs", label: "Jobs" },
  { value: "diagnostics", label: "Diagnostics" },
]

const statusFilters: Array<{ value: string; label: string; statuses?: JobStatus[] }> = [
  { value: "all", label: "All statuses" },
  { value: "queued", label: "Queued", statuses: ["queued"] },
  { value: "running", label: "Running", statuses: ["running"] },
  { value: "attention", label: "Needs attention", statuses: ["failed", "needs_review"] },
  { value: "succeeded", label: "Succeeded", statuses: ["succeeded"] },
  { value: "cancelled", label: "Cancelled", statuses: ["cancelled"] },
]

export function OperationsCenter({ initialQuery = {} }: { initialQuery?: OperationsQuery }) {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const { timezone } = useDateTime()
  const triggerRef = useRef<HTMLButtonElement | null>(null)

  const param = useCallback(
    (key: keyof OperationsQuery) => searchParams ? searchParams.get(key) : initialQuery[key] ?? null,
    [initialQuery, searchParams],
  )
  const view = normalizeView(param("view"))
  const selectedId = param("job")
  const status = normalizeStatusFilter(param("status"))
  const jobType = param("type") ?? "all"
  const dateRange = normalizeDateRange(param("range"))
  const failedOnly = param("failed") === "true"
  const [searchText, setSearchText] = useState(param("search") ?? "")
  const [issueSeverity, setIssueSeverity] = useState("all")
  const [issueComponent, setIssueComponent] = useState("all")
  const [issueWindow, setIssueWindow] = useState<DateRange>("all")
  const [announcement, setAnnouncement] = useState("")

  useEffect(() => setSearchText(param("search") ?? ""), [param])

  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs({ limit: 250 }),
    queryFn: () => getJobs({ limit: 250 }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => query.state.data?.some(isActiveJob) ? 5_000 : false,
    refetchIntervalInBackground: false,
  })
  const summaryQuery = useQuery({
    queryKey: queryKeys.jobSummary,
    queryFn: getJobSummary,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  })
  const diagnosticsQuery = useQuery({
    queryKey: operationsQueryKeys.diagnostics,
    queryFn: fetchOperationsDiagnostics,
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })
  const healthQuery = useQuery({
    queryKey: operationsQueryKeys.health,
    queryFn: fetchOperationalHealth,
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })
  const detailQuery = useQuery({
    queryKey: selectedId ? queryKeys.job(selectedId) : ["jobs", "detail", "none"],
    queryFn: () => getJob(selectedId as string),
    enabled: Boolean(selectedId),
    refetchInterval: (query) => query.state.data && isActiveJob(query.state.data) ? 5_000 : false,
    refetchIntervalInBackground: false,
  })

  const updateUrl = useCallback((updates: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams?.toString() ?? "")
    for (const [key, value] of Object.entries(updates)) {
      if (!value || value === "all" || (key === "view" && value === "overview")) next.delete(key)
      else next.set(key, value)
    }
    const query = next.toString()
    router.replace(`${pathname}${query ? `?${query}` : ""}`, { scroll: false })
  }, [pathname, router, searchParams])

  const invalidateJobTruth = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["jobs"] })
    if (selectedId) await queryClient.invalidateQueries({ queryKey: queryKeys.job(selectedId) })
    await queryClient.invalidateQueries({ queryKey: operationsQueryKeys.diagnostics })
    await queryClient.invalidateQueries({ queryKey: operationsQueryKeys.health })
  }, [queryClient, selectedId])

  const retryMutation = useMutation({
    mutationFn: (id: string) => retryJob(id),
    onSuccess: async () => {
      await invalidateJobTruth()
      pushNotice({ tone: "success", title: "Retry requested", message: "Job returned to the durable queue." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Retry failed", message: getApiErrorMessage(error) }),
  })
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelJob(id),
    onSuccess: async () => {
      await invalidateJobTruth()
      pushNotice({ tone: "success", title: "Job cancelled", message: "Queued job was cancelled." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Cancellation failed", message: getApiErrorMessage(error) }),
  })

  const allJobs = jobsQuery.data ?? []
  const filteredJobs = useMemo(
    () => filterJobs(allJobs, { status, jobType, dateRange, searchText, failedOnly }),
    [allJobs, dateRange, failedOnly, jobType, searchText, status],
  )
  const jobTypes = useMemo(() => [...new Set(allJobs.map((job) => job.job_type))].sort(), [allJobs])
  const issues = useMemo(
    () => collectIssues(diagnosticsQuery.data, healthQuery.data),
    [diagnosticsQuery.data, healthQuery.data],
  )
  const issueComponents = useMemo(() => [...new Set(issues.map((issue) => issue.component))].sort(), [issues])
  const visibleIssues = useMemo(
    () => filterIssues(issues, issueSeverity, issueComponent, issueWindow),
    [issueComponent, issueSeverity, issueWindow, issues],
  )
  const lastRefresh = oldestSuccessfulUpdate(
    jobsQuery.dataUpdatedAt,
    summaryQuery.dataUpdatedAt,
    diagnosticsQuery.dataUpdatedAt,
    healthQuery.dataUpdatedAt,
  )
  const refreshing = jobsQuery.isFetching || summaryQuery.isFetching || diagnosticsQuery.isFetching || healthQuery.isFetching

  const refreshAll = async () => {
    await Promise.all([
      jobsQuery.refetch(),
      summaryQuery.refetch(),
      diagnosticsQuery.refetch(),
      healthQuery.refetch(),
    ])
    setAnnouncement("Operations data refreshed.")
  }
  const runDiagnostics = async () => {
    const results = await Promise.all([diagnosticsQuery.refetch(), healthQuery.refetch()])
    const failed = results.some((result) => result.isError)
    setAnnouncement(failed ? "Some diagnostic checks could not be refreshed." : "System checks completed.")
  }

  const selectJob = (job: WorkflowJob, trigger: HTMLButtonElement) => {
    triggerRef.current = trigger
    updateUrl({ job: job.id, view: "jobs" })
  }
  const closeJob = () => {
    updateUrl({ job: null })
    window.requestAnimationFrame(() => triggerRef.current?.focus())
  }

  return (
    <OperationsPageFrame
      title="Operations Center"
      subtitle="Monitor jobs, run system checks, and resolve operational failures."
      actions={(
        <>
          <Button disabled={refreshing} onClick={() => void refreshAll()} size="sm" variant="outline">
            <RefreshCw aria-hidden="true" className={cn(refreshing && "animate-spin motion-reduce:animate-none")} />
            Refresh
          </Button>
          <Button disabled={diagnosticsQuery.isFetching || healthQuery.isFetching} onClick={() => void runDiagnostics()} size="sm">
            <Activity aria-hidden="true" />
            {diagnosticsQuery.isFetching || healthQuery.isFetching ? "Running…" : "Run diagnostics"}
          </Button>
        </>
      )}
    >
      <div aria-live="polite" className="sr-only">{announcement}</div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Operations Center views" className="inline-flex rounded-md border border-border/70 bg-muted/35 p-1">
          {viewLabels.map((item) => (
            <Link
              aria-current={view === item.value ? "page" : undefined}
              className={cn(
                "inline-flex min-h-11 items-center rounded px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 min-[900px]:min-h-10",
                view === item.value && "bg-accent text-accent-foreground shadow-sm",
              )}
              href={viewHref(item.value, searchParams)}
              key={item.value}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="text-xs text-muted-foreground">
          {lastRefresh ? <>Last successful refresh <time dateTime={new Date(lastRefresh).toISOString()}>{formatInTimeZone(lastRefresh, timezone)}</time></> : "Waiting for first successful refresh"}
        </p>
      </div>

      <OperationsSummary
        health={healthQuery.data}
        summary={summaryQuery.data}
      />

      <QueryFailureSummary
        diagnosticsError={diagnosticsQuery.error}
        healthError={healthQuery.error}
        jobsError={jobsQuery.error}
        summaryError={summaryQuery.error}
        onRetry={() => void refreshAll()}
      />

      {view === "overview" ? (
        <div className="space-y-5">
          <IssueCenter
            components={issueComponents}
            issues={visibleIssues}
            selectedComponent={issueComponent}
            selectedSeverity={issueSeverity}
            selectedWindow={issueWindow}
            onComponentChange={setIssueComponent}
            onSeverityChange={setIssueSeverity}
            onWindowChange={setIssueWindow}
          />
          <SectionCard title="Recent and active jobs" action={<Link className="inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline min-[900px]:min-h-0" href="/operations?view=jobs">View all jobs</Link>}>
            <JobsResult
              jobs={prioritizeJobs(allJobs).slice(0, 8)}
              query={jobsQuery}
              selectedId={selectedId}
              onSelect={selectJob}
              emptyTitle="No active jobs"
              emptyDescription="Queued or running work will appear here."
            />
          </SectionCard>
          <SectionCard title="System checks" action={<Link className="inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline min-[900px]:min-h-0" href="/operations?view=diagnostics">View all checks</Link>}>
            <DiagnosticChecks health={healthQuery.data} snapshot={diagnosticsQuery.data} compact />
          </SectionCard>
        </div>
      ) : null}

      {view === "jobs" ? (
        <section aria-labelledby="jobs-workspace-heading" className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold" id="jobs-workspace-heading">Jobs</h2>
            <p className="text-sm text-muted-foreground">Recent durable work, failures, retry state, and safe operator actions.</p>
          </div>
          <JobFilters
            dateRange={dateRange}
            failedOnly={failedOnly}
            jobType={jobType}
            jobTypes={jobTypes}
            searchText={searchText}
            status={status}
            onDateRangeChange={(value) => updateUrl({ range: value })}
            onFailedOnlyChange={(value) => updateUrl({ failed: value ? "true" : null })}
            onJobTypeChange={(value) => updateUrl({ type: value })}
            onReset={() => {
              setSearchText("")
              updateUrl({ status: null, type: null, range: null, search: null, failed: null })
            }}
            onSearchChange={setSearchText}
            onSearchCommit={() => updateUrl({ search: searchText.trim() || null })}
            onStatusChange={(value) => updateUrl({ status: value })}
          />
          <Card className="overflow-hidden rounded-md py-0" size="sm">
            <CardContent className="p-0">
              <JobsResult
                jobs={filteredJobs}
                query={jobsQuery}
                selectedId={selectedId}
                onSelect={selectJob}
                emptyTitle="No jobs match these filters"
                emptyDescription="Reset filters or choose a broader time range."
              />
            </CardContent>
          </Card>
        </section>
      ) : null}

      {view === "diagnostics" ? (
        <section aria-labelledby="diagnostics-workspace-heading" className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold" id="diagnostics-workspace-heading">System checks</h2>
            <p className="text-sm text-muted-foreground">Safe, allowlisted readiness and runtime observations grouped by component.</p>
          </div>
          {healthQuery.isPending && !healthQuery.data ? <LoadingState aria-label="Loading operational diagnostics" title="Loading system checks…" /> : null}
          {healthQuery.isError && !healthQuery.data ? (
            <ErrorState
              dir="auto"
              title="Diagnostics are temporarily unavailable"
              description={getApiErrorMessage(healthQuery.error, "Retry the request or check API readiness.")}
              action={<Button onClick={() => void runDiagnostics()} size="sm" variant="outline">Retry diagnostics</Button>}
            />
          ) : null}
          <DiagnosticChecks health={healthQuery.data} snapshot={diagnosticsQuery.data} />
        </section>
      ) : null}

      {selectedId ? (
        <JobDetailPanel
          job={detailQuery.data}
          isLoading={detailQuery.isPending}
          error={detailQuery.error}
          mutationPending={retryMutation.isPending || cancelMutation.isPending}
          onClose={closeJob}
          onRetry={() => {
            if (window.confirm("Retry this failed job using its existing durable payload?")) retryMutation.mutate(selectedId)
          }}
          onCancel={() => {
            if (window.confirm("Cancel this queued job? This stops it from being claimed.")) cancelMutation.mutate(selectedId)
          }}
        />
      ) : null}
    </OperationsPageFrame>
  )
}

function OperationsSummary({
  health,
  summary,
}: {
  health?: OperationalHealthSnapshot
  summary?: Awaited<ReturnType<typeof getJobSummary>>
}) {
  const workers = Object.values(health?.components ?? {}).filter((component) => component.component_type === "worker")
  const onlineWorkers = workers.filter((component) => component.state === "healthy").length
  const metrics = [
    { label: "System health", value: health ? healthLabel(health.state) : "Unknown", href: "/operations?view=diagnostics", tone: healthTone(health?.state) },
    { label: "Running jobs", value: summary?.running ?? "—", href: "/operations?view=jobs&status=running", tone: "neutral" as StatusTone },
    { label: "Queued jobs", value: summary?.queued ?? "—", href: "/operations?view=jobs&status=queued", tone: "neutral" as StatusTone },
    { label: "Failed jobs", value: summary?.attention ?? "—", href: "/operations?view=jobs&status=attention", tone: summary?.attention ? "error" as StatusTone : "success" as StatusTone },
    { label: "Workers online", value: health ? `${onlineWorkers} of ${workers.length}` : "Unknown", href: "/operations?view=diagnostics", tone: workers.length > 0 && onlineWorkers === workers.length ? "success" as StatusTone : "warning" as StatusTone },
  ]

  return (
    <section aria-label="Operational status summary" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {metrics.map((metric) => (
        <Link className="group rounded-md border border-border/60 bg-card p-3 transition-colors hover:bg-muted/35 focus-visible:ring-2 focus-visible:ring-ring/60" href={metric.href} key={metric.label}>
          <div className="text-xs text-muted-foreground">{metric.label}</div>
          <div className="mt-1 flex items-center justify-between gap-2 font-semibold tabular-nums">
            <span>{metric.value}</span>
            <span aria-hidden="true" className={cn("size-2 rounded-full", toneDot(metric.tone))} />
          </div>
        </Link>
      ))}
    </section>
  )
}

function IssueCenter({
  components,
  issues,
  selectedComponent,
  selectedSeverity,
  selectedWindow,
  onComponentChange,
  onSeverityChange,
  onWindowChange,
}: {
  components: string[]
  issues: Issue[]
  selectedComponent: string
  selectedSeverity: string
  selectedWindow: DateRange
  onComponentChange: (value: string) => void
  onSeverityChange: (value: string) => void
  onWindowChange: (value: DateRange) => void
}) {
  return (
    <section aria-labelledby="issues-heading" className="overflow-hidden rounded-md border border-border/70 bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-3 py-3 sm:px-4">
        <div>
          <h2 className="font-semibold" id="issues-heading">Actionable issues</h2>
          <p className="text-xs text-muted-foreground">Current failures from canonical health, job, and dependency records.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <CompactSelect ariaLabel="Filter issues by severity" value={selectedSeverity} onChange={onSeverityChange} options={[{ value: "all", label: "All severities" }, { value: "error", label: "Errors" }, { value: "warning", label: "Warnings" }]} />
          <CompactSelect ariaLabel="Filter issues by component" value={selectedComponent} onChange={onComponentChange} options={[{ value: "all", label: "All components" }, ...components.map((component) => ({ value: component, label: component }))]} />
          <CompactSelect ariaLabel="Filter issues by time" value={selectedWindow} onChange={(value) => onWindowChange(normalizeDateRange(value))} options={[{ value: "all", label: "All time" }, { value: "24h", label: "Last 24 hours" }, { value: "7d", label: "Last 7 days" }, { value: "30d", label: "Last 30 days" }]} />
        </div>
      </div>
      {issues.length ? (
        <ul className="divide-y divide-border/50">
          {issues.map((issue) => (
            <li className="grid gap-3 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-4" key={issue.key}>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone={issue.severity === "error" ? "error" : "warning"}>{issue.severity === "error" ? "Unavailable" : "Needs attention"}</StatusBadge>
                  <span className="text-xs font-medium text-muted-foreground">{issue.component}</span>
                </div>
                <p className="mt-1 font-medium" dir="auto">{issue.title}</p>
                {issue.explanation ? <p className="mt-1 text-sm text-muted-foreground" dir="auto">{issue.explanation}</p> : null}
                <time className="mt-1 block text-xs text-muted-foreground" dateTime={issue.occurredAt}>{formatRelativeTime(issue.occurredAt)}</time>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {issue.code ? <CopyButton label="Copy error code" value={issue.code} /> : null}
                {issue.actionHref ? <Link className="inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium text-primary hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/60 min-[900px]:min-h-10" href={normalizeLegacyHref(issue.actionHref)}>{issue.actionLabel ?? "Inspect"}</Link> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState className="m-3" title="No current operational issues" description="Recent jobs and system checks are healthy." />
      )}
    </section>
  )
}

function JobFilters({
  dateRange,
  failedOnly,
  jobType,
  jobTypes,
  searchText,
  status,
  onDateRangeChange,
  onFailedOnlyChange,
  onJobTypeChange,
  onReset,
  onSearchChange,
  onSearchCommit,
  onStatusChange,
}: {
  dateRange: DateRange
  failedOnly: boolean
  jobType: string
  jobTypes: string[]
  searchText: string
  status: string
  onDateRangeChange: (value: string) => void
  onFailedOnlyChange: (value: boolean) => void
  onJobTypeChange: (value: string) => void
  onReset: () => void
  onSearchChange: (value: string) => void
  onSearchCommit: () => void
  onStatusChange: (value: string) => void
}) {
  return (
    <div aria-label="Job filters" className="grid gap-2 rounded-md border border-border/60 bg-card p-3 sm:grid-cols-2 lg:grid-cols-[minmax(12rem,1.5fr)_repeat(3,minmax(9rem,1fr))_auto]" role="group">
      <label className="relative min-w-0">
        <span className="sr-only">Search jobs</span>
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-3.5 size-4 text-muted-foreground" />
        <Input
          className="h-11 pl-9"
          onBlur={onSearchCommit}
          onChange={(event) => onSearchChange(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") onSearchCommit() }}
          placeholder="Search type, ID, or safe error"
          value={searchText}
        />
      </label>
      <CompactSelect ariaLabel="Filter jobs by status" value={status} onChange={onStatusChange} options={statusFilters.map(({ value, label }) => ({ value, label }))} />
      <CompactSelect ariaLabel="Filter jobs by type" value={jobType} onChange={onJobTypeChange} options={[{ value: "all", label: "All job types" }, ...jobTypes.map((type) => ({ value: type, label: humanize(type) }))]} />
      <CompactSelect ariaLabel="Filter jobs by date range" value={dateRange} onChange={onDateRangeChange} options={[{ value: "all", label: "All dates" }, { value: "24h", label: "Last 24 hours" }, { value: "7d", label: "Last 7 days" }, { value: "30d", label: "Last 30 days" }]} />
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-1 lg:justify-end">
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-border/70 px-3 text-sm">
          <input checked={failedOnly} onChange={(event) => onFailedOnlyChange(event.target.checked)} type="checkbox" />
          Failed only
        </label>
        <Button onClick={onReset} variant="ghost">Reset</Button>
      </div>
    </div>
  )
}

function JobsResult({
  jobs,
  query,
  selectedId,
  onSelect,
  emptyTitle,
  emptyDescription,
}: {
  jobs: WorkflowJob[]
  query: UseQueryResult<WorkflowJob[], Error>
  selectedId: string | null
  onSelect: (job: WorkflowJob, trigger: HTMLButtonElement) => void
  emptyTitle: string
  emptyDescription: string
}) {
  if (query.isPending && !query.data) return <LoadingState aria-label="Loading jobs" className="m-3" title="Loading jobs…" />
  if (query.isError && !query.data) {
    return <ErrorState className="m-3" title="Jobs could not be loaded" description={getApiErrorMessage(query.error, "Job request failed")} dir="auto" />
  }
  if (!jobs.length) return <EmptyState className="m-3" title={emptyTitle} description={emptyDescription} />
  return <JobTable jobs={jobs} selectedId={selectedId} onSelect={onSelect} />
}

function DiagnosticChecks({ health, snapshot, compact = false }: { health?: OperationalHealthSnapshot; snapshot?: OperationsSnapshot; compact?: boolean }) {
  const groups = diagnosticGroups(health, snapshot)
  const visibleGroups = compact ? groups.map((group) => ({ ...group, checks: group.checks.slice(0, 3) })).filter((group) => group.checks.length).slice(0, 2) : groups

  if (!health && !snapshot) return <EmptyState className="m-3" title="Diagnostics unavailable" description="Run diagnostics to request a fresh system snapshot." />

  return (
    <div className={cn("divide-y divide-border/50", !compact && "overflow-hidden rounded-md border border-border/70 bg-card")}>
      {visibleGroups.map((group) => (
        <section aria-labelledby={`check-group-${group.id}`} key={group.id}>
          <div className="bg-muted/25 px-3 py-2 sm:px-4">
            <h3 className="text-sm font-semibold" id={`check-group-${group.id}`}>{group.label}</h3>
          </div>
          <div className="divide-y divide-border/50">
            {group.checks.map((check) => <DiagnosticRow check={check} key={check.id} />)}
          </div>
        </section>
      ))}
      {!compact ? <p className="px-3 py-3 text-xs text-muted-foreground sm:px-4">Checks refresh together because current server contract exposes bounded, allowlisted snapshots rather than arbitrary run-one execution.</p> : null}
    </div>
  )
}

type DiagnosticCheck = {
  id: string
  name: string
  component: string
  state: OperationalHealthState
  code: string
  observedAt: string | null
  durationMs: number | null
  message: string
}

function DiagnosticRow({ check }: { check: DiagnosticCheck }) {
  return (
    <article className="grid gap-2 px-3 py-3 sm:grid-cols-[minmax(11rem,0.9fr)_minmax(0,1.4fr)_auto] sm:items-center sm:px-4">
      <div className="min-w-0">
        <h4 className="font-medium">{check.name}</h4>
        <p className="text-xs text-muted-foreground">{check.component}</p>
      </div>
      <div className="min-w-0">
        <p className="break-words text-sm text-muted-foreground" dir="auto">{check.message}</p>
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          <span>{check.observedAt ? <>Checked <time dateTime={check.observedAt}>{formatRelativeTime(check.observedAt)}</time></> : "No trustworthy observation"}</span>
          {check.durationMs !== null ? <span>{check.durationMs} ms</span> : null}
        </div>
      </div>
      <div className="flex items-center gap-2 sm:justify-end">
        <StatusBadge tone={healthTone(check.state)}>{healthLabel(check.state)}</StatusBadge>
        {check.state !== "healthy" ? <CopyButton label={`Copy ${check.name} error code`} value={check.code} /> : null}
      </div>
    </article>
  )
}

function SectionCard({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="overflow-hidden rounded-md py-0" size="sm">
      <CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/60 px-3 py-3 sm:px-4">
        <CardTitle className="text-base">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  )
}

function QueryFailureSummary({ diagnosticsError, healthError, jobsError, summaryError, onRetry }: { diagnosticsError: Error | null; healthError: Error | null; jobsError: Error | null; summaryError: Error | null; onRetry: () => void }) {
  const failures = [
    diagnosticsError && "operational projection",
    healthError && "system checks",
    jobsError && "job list",
    summaryError && "job summary",
  ].filter(Boolean)
  if (!failures.length) return null
  return (
    <Alert tone="error" role="alert">
      <XCircle aria-hidden="true" />
      <div className="min-w-0">
        <AlertTitle>Some operational data is unavailable</AlertTitle>
        <AlertDescription>{failures.join(", ")}. Existing visible data may be stale.</AlertDescription>
      </div>
      <Button onClick={onRetry} size="sm" variant="outline">Retry</Button>
    </Alert>
  )
}

function CompactSelect({ ariaLabel, value, options, onChange }: { ariaLabel: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
  return (
    <select aria-label={ariaLabel} className="h-11 max-w-full rounded-md border border-border/70 bg-background px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring/60" onChange={(event) => onChange(event.target.value)} value={value}>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  )
}

function CopyButton({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      aria-label={copied ? "Copied" : label}
      onClick={() => {
        void navigator.clipboard?.writeText(value)
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1_500)
      }}
      size="icon-sm"
      title={copied ? "Copied" : label}
      variant="ghost"
    >
      {copied ? <CheckCircle2 aria-hidden="true" /> : <Clipboard aria-hidden="true" />}
    </Button>
  )
}

function diagnosticGroups(health?: OperationalHealthSnapshot, snapshot?: OperationsSnapshot) {
  const core: DiagnosticCheck[] = []
  const workers: DiagnosticCheck[] = []
  const content: DiagnosticCheck[] = []
  const configuration: DiagnosticCheck[] = []

  if (health) {
    core.push({ id: "api", name: "API response", component: "API", state: "healthy", code: "api_available", observedAt: health.generated_at, durationMs: null, message: "Operations health snapshot returned successfully." })
    for (const [name, dependency] of Object.entries(health.dependencies)) {
      const check = dependencyCheck(name, dependency)
      if (name === "database" || name === "schema") core.push(check)
      else if (name.startsWith("capability:")) content.push(check)
      else configuration.push(check)
    }
    if (health.queues.length) core.push(queueCheck(health.queues, health.generated_at))
    for (const component of Object.values(health.components)) workers.push(componentCheck(component))
  } else if (snapshot) {
    core.push({ id: "api", name: "API response", component: "API", state: "healthy", code: "api_available", observedAt: snapshot.generated_at, durationMs: null, message: "Operations diagnostic snapshot returned successfully." })
    for (const [id, component] of Object.entries(snapshot.components)) {
      workers.push({ id, name: humanize(id), component: id.includes("scheduler") ? "Scheduler" : "Workers", state: legacyHealthState(component.status), code: `heartbeat_${component.status}`, observedAt: component.observed_at, durationMs: null, message: component.message })
    }
  }

  if (snapshot) {
    const proxy = snapshot.outbound_proxy
    configuration.push({
      id: "outbound-proxy",
      name: "Outbound network policy",
      component: "Network",
      state: proxy.configuration_error_code || proxy.last_connectivity_status === "failed" ? "unavailable" : proxy.last_connectivity_status === "not_checked" ? "unknown" : "healthy",
      code: proxy.configuration_error_code ?? `proxy_${proxy.last_connectivity_status}`,
      observedAt: snapshot.generated_at,
      durationMs: null,
      message: proxy.configuration_error_code ? "Outbound proxy configuration is invalid." : `${proxy.mode === "direct" ? "Direct routing" : "Configured proxy"}; ${humanize(proxy.last_connectivity_status)}.`,
    })
  }

  return [
    { id: "core", label: "Core services", checks: core },
    { id: "workers", label: "Workers and scheduler", checks: workers },
    { id: "content", label: "Content dependencies", checks: content },
    { id: "configuration", label: "Configuration and storage", checks: configuration },
  ].filter((group) => group.checks.length)
}

function dependencyCheck(name: string, dependency: OperationalDependency): DiagnosticCheck {
  return { id: `dependency:${name}`, name: humanize(name.replace("capability:", "")), component: name.startsWith("capability:") ? "Provider readiness" : "Dependency", state: dependency.state, code: dependency.code, observedAt: dependency.observed_at, durationMs: dependency.latency_ms, message: dependency.message }
}

function componentCheck(component: OperationalComponent): DiagnosticCheck {
  return { id: `component:${component.component_id}`, name: humanize(component.component_id), component: component.component_type === "scheduler" ? "Scheduler" : "Workers", state: component.state, code: component.code, observedAt: component.observed_at, durationMs: null, message: component.message }
}

function queueCheck(queues: OperationalQueue[], observedAt: string): DiagnosticCheck {
  const state = worstState(queues.map((queue) => queue.state))
  const due = queues.reduce((sum, queue) => sum + queue.due_count, 0)
  const running = queues.reduce((sum, queue) => sum + queue.running_count, 0)
  const unhealthy = queues.filter((queue) => queue.state !== "healthy")
  return { id: "queue", name: "Durable job queue", component: "Queue", state, code: unhealthy[0]?.code ?? "queue_healthy", observedAt, durationMs: null, message: `${due} due, ${running} running${unhealthy.length ? `, ${unhealthy.length} job types need attention` : ""}.` }
}

function collectIssues(snapshot?: OperationsSnapshot, health?: OperationalHealthSnapshot): Issue[] {
  const issues = new Map<string, Issue>()
  for (const item of snapshot?.attention ?? []) {
    const key = item.kind === "job" || /^[0-9a-f-]{36}$/i.test(item.id) ? `job:${item.id.replace("job:", "")}` : item.id
    issues.set(key, { key, title: item.title, component: issueComponentName(item.kind), severity: item.severity, occurredAt: item.occurred_at, actionHref: item.action_url, actionLabel: attentionActionLabel(item.kind), explanation: "Review related operational evidence and follow the linked recovery path." })
  }
  for (const alert of health?.alerts ?? []) {
    const key = alert.scope.startsWith("job:") ? alert.scope : `${alert.scope}:${alert.code}`
    if (issues.has(key)) continue
    issues.set(key, { key, title: alert.message, component: humanize(alert.scope.split(":")[0]), severity: alert.state === "unavailable" ? "error" : "warning", occurredAt: health?.generated_at ?? new Date().toISOString(), code: alert.code, actionHref: alert.scope.startsWith("job:") ? `/operations?view=jobs&job=${alert.scope.slice(4)}` : "/operations?view=diagnostics", actionLabel: alert.scope.startsWith("job:") ? "Open job" : "Inspect check", explanation: recoveryForScope(alert.scope) })
  }
  return [...issues.values()].sort((a, b) => Date.parse(b.occurredAt) - Date.parse(a.occurredAt))
}

function filterJobs(jobs: WorkflowJob[], filters: { status: string; jobType: string; dateRange: DateRange; searchText: string; failedOnly: boolean }) {
  const statuses = statusFilters.find((filter) => filter.value === filters.status)?.statuses
  const cutoff = dateCutoff(filters.dateRange)
  const needle = filters.searchText.trim().toLocaleLowerCase()
  return jobs.filter((job) => {
    if (statuses && !statuses.includes(job.status)) return false
    if (filters.failedOnly && !["failed", "needs_review"].includes(job.status)) return false
    if (filters.jobType !== "all" && job.job_type !== filters.jobType) return false
    if (cutoff && Date.parse(job.created_at) < cutoff) return false
    if (needle && ![job.id, job.job_type, job.error_code, job.error_message, job.progress_message].filter(Boolean).some((value) => String(value).toLocaleLowerCase().includes(needle))) return false
    return true
  })
}

function filterIssues(issues: Issue[], severity: string, component: string, window: DateRange) {
  const cutoff = dateCutoff(window)
  return issues.filter((issue) => (severity === "all" || issue.severity === severity) && (component === "all" || issue.component === component) && (!cutoff || Date.parse(issue.occurredAt) >= cutoff))
}

function prioritizeJobs(jobs: WorkflowJob[]) {
  const priority: Record<JobStatus, number> = { failed: 0, needs_review: 1, running: 2, queued: 3, succeeded: 4, cancelled: 5 }
  return [...jobs].sort((a, b) => priority[a.status] - priority[b.status] || Date.parse(b.updated_at) - Date.parse(a.updated_at))
}

function viewHref(view: OperationsView, params: { toString(): string } | null) {
  const next = new URLSearchParams(params?.toString() ?? "")
  if (view === "overview") next.delete("view")
  else next.set("view", view)
  const query = next.toString()
  return `/operations${query ? `?${query}` : ""}`
}

function normalizeLegacyHref(href: string) {
  if (href.startsWith("/jobs")) {
    const [pathAndQuery, hash] = href.split("#", 2)
    const [, query = ""] = pathAndQuery.split("?", 2)
    const params = new URLSearchParams(query)
    params.set("view", "jobs")
    return `/operations?${params.toString()}${hash ? `#${hash}` : ""}`
  }
  if (href.startsWith("/diagnostics")) return href.replace("/diagnostics", "/operations?view=diagnostics")
  return href
}

function normalizeView(value: string | null): OperationsView {
  return value === "jobs" || value === "diagnostics" ? value : "overview"
}

function normalizeStatusFilter(value: string | null) {
  if (value === "failed" || value === "needs_review") return "attention"
  return statusFilters.some((filter) => filter.value === value) ? value as string : "all"
}

function normalizeDateRange(value: string | null): DateRange {
  return value === "24h" || value === "7d" || value === "30d" ? value : "all"
}

function isActiveJob(job: WorkflowJob) {
  return job.status === "queued" || job.status === "running"
}

function dateCutoff(range: DateRange) {
  const duration = range === "24h" ? 86_400_000 : range === "7d" ? 604_800_000 : range === "30d" ? 2_592_000_000 : 0
  return duration ? Date.now() - duration : 0
}

function formatRelativeTime(value: string) {
  const time = Date.parse(value)
  if (!Number.isFinite(time)) return value
  const seconds = Math.round((time - Date.now()) / 1_000)
  const absolute = Math.abs(seconds)
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
  if (absolute < 60) return formatter.format(seconds, "second")
  if (absolute < 3_600) return formatter.format(Math.round(seconds / 60), "minute")
  if (absolute < 86_400) return formatter.format(Math.round(seconds / 3_600), "hour")
  return formatter.format(Math.round(seconds / 86_400), "day")
}

function oldestSuccessfulUpdate(...values: number[]) {
  const successful = values.filter((value) => value > 0)
  return successful.length ? Math.min(...successful) : 0
}

function healthLabel(state?: OperationalHealthState) {
  if (!state) return "Unknown"
  return state.charAt(0).toUpperCase() + state.slice(1)
}

function healthTone(state?: OperationalHealthState): StatusTone {
  if (state === "healthy") return "success"
  if (state === "unavailable") return "error"
  if (state === "stale") return "warning"
  return "neutral"
}

function toneDot(tone: StatusTone) {
  if (tone === "success") return "bg-success"
  if (tone === "error") return "bg-destructive"
  if (tone === "warning") return "bg-warning"
  return "bg-muted-foreground"
}

function legacyHealthState(status: "healthy" | "degraded" | "down" | "unknown"): OperationalHealthState {
  if (status === "healthy") return "healthy"
  if (status === "degraded") return "stale"
  if (status === "down") return "unavailable"
  return "unknown"
}

function worstState(states: OperationalHealthState[]): OperationalHealthState {
  if (states.includes("unavailable")) return "unavailable"
  if (states.includes("stale")) return "stale"
  if (states.includes("unknown")) return "unknown"
  return "healthy"
}

function issueComponentName(kind: OperationsSnapshot["attention"][number]["kind"]) {
  if (kind === "job" || kind === "research" || kind === "generation") return "Jobs"
  if (kind === "publication" || kind === "destination") return "Publishing"
  if (kind === "source") return "Sources"
  if (kind === "route") return "Automations"
  return humanize(kind)
}

function attentionActionLabel(kind: OperationsSnapshot["attention"][number]["kind"]) {
  if (["job", "research", "generation"].includes(kind)) return "View affected job"
  if (kind === "source") return "Open source"
  if (kind === "route") return "Open automation"
  return "Open recovery path"
}

function recoveryForScope(scope: string) {
  if (scope.startsWith("dependency:")) return "Restore dependency readiness, then run diagnostics again."
  if (scope.startsWith("component:")) return "Check worker or scheduler supervision and wait for a fresh heartbeat."
  if (scope.startsWith("queue:")) return "Inspect affected jobs and compatible worker availability."
  return "Inspect safe failure details before retrying work."
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replaceAll(".", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
