"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  Gauge,
  Infinity,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react"

import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { getArticleCardTime } from "@/features/articles/article-card-metadata"
import { getArticles } from "@/features/articles/api"
import type { ArticleSummary } from "@/features/articles/types"
import { getAutomations } from "@/features/automations/automation-api"
import type { Automation } from "@/features/automations/automation-types"
import { getJobSummary } from "@/features/jobs/api"
import { fetchOperationsDiagnostics } from "@/features/operations/api"
import {
  getIngestRuns,
  getSourceCollections,
  getSourcePage,
} from "@/features/operations/ingestion-api"
import type {
  IngestRunSummary,
  SourceCollectionSummary,
} from "@/features/operations/ingestion-api"
import type { OperationsSnapshot } from "@/features/operations/types"
import { getApiErrorMessage } from "@/lib/http"
import { safeHttpUrl } from "@/lib/url"
import { formatInTimeZone } from "@/lib/date-time"
import { formatNumber, titleCase } from "@/lib/format"
import { operationsQueryKeys, queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"

const TODAY_ARTICLE_LIMIT = 9
const TODAY_AUTOMATION_LIMIT = 6
const TODAY_INGEST_RUN_LIMIT = 6

type QueryView<T> = {
  data: T | undefined
  isPending: boolean
  isError: boolean
  error: unknown
  retry: () => void
}

type QueryLike<T> = {
  data: T | undefined
  isPending: boolean
  isError: boolean
  error: unknown
  refetch: () => Promise<unknown>
}

export function TodayPage() {
  const { timezone } = useDateTime()
  const [selectedArticle, setSelectedArticle] = useState<ArticleSummary | null>(null)
  const articlesQuery = useQuery({
    queryKey: queryKeys.articlesToday(TODAY_ARTICLE_LIMIT),
    queryFn: ({ signal }) => getArticles({ sort: "newest", limit: TODAY_ARTICLE_LIMIT }, signal),
    staleTime: 30_000,
  })
  const sourcesQuery = useQuery({
    queryKey: queryKeys.sourcesToday,
    queryFn: ({ signal }) => getSourcePage({ limit: 1 }, signal),
    staleTime: 30_000,
  })
  const collectionsQuery = useQuery({
    queryKey: queryKeys.sourceCollections,
    queryFn: ({ signal }) => getSourceCollections(signal),
    staleTime: 30_000,
  })
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobSummary,
    queryFn: getJobSummary,
    staleTime: 15_000,
  })
  const diagnosticsQuery = useQuery({
    queryKey: operationsQueryKeys.diagnostics,
    queryFn: fetchOperationsDiagnostics,
    staleTime: 15_000,
  })
  const automationsQuery = useQuery({
    queryKey: queryKeys.automations({ limit: TODAY_AUTOMATION_LIMIT }),
    queryFn: ({ signal }) => getAutomations({ limit: TODAY_AUTOMATION_LIMIT }, signal),
    staleTime: 30_000,
  })
  const ingestRunsQuery = useQuery({
    queryKey: queryKeys.ingestRunsToday(TODAY_INGEST_RUN_LIMIT),
    queryFn: ({ signal }) => getIngestRuns(TODAY_INGEST_RUN_LIMIT, signal),
    staleTime: 15_000,
  })

  const articles = articlesQuery.data?.items ?? []
  const sourceCount = sourcesQuery.data?.total
  const collectionCount = collectionsQuery.data?.length
  const continuousCollectionCount = collectionsQuery.data?.filter(
    (collection) => collection.continuousSubscriptionId !== null,
  ).length
  const automationCount = automationsQuery.data?.items.length

  return (
    <>
      <section className="nc-page min-h-full gap-5" aria-labelledby="today-heading">
        <TodayHeader timezone={timezone} />
        {articlesQuery.isPending ? (
          <div role="status" aria-label="Loading Today" className="sr-only">
            Loading Today
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Newsroom overview metrics">
          <MetricCard
            icon={FileText}
            label="Articles available"
            value={metricValue(articlesQuery.data?.resultCount)}
            detail={metricDetail(articlesQuery, "Newest article results")}
          />
          <MetricCard
            icon={Database}
            label="Tracked sources"
            value={metricValue(sourceCount)}
            detail={metricDetail(sourcesQuery, "Source registry")}
          />
          <MetricCard
            icon={AlertTriangle}
            label="Jobs needing attention"
            value={metricValue(jobsQuery.data?.attention)}
            detail={metricDetail(jobsQuery, "Live job summary")}
          />
          <MetricCard
            icon={Workflow}
            label="Automations shown"
            value={metricValue(automationCount)}
            detail={
              automationsQuery.isError
                ? "Unavailable"
                : automationsQuery.data?.nextCursor
                  ? "More records available"
                  : "Live API list"
            }
          />
          <MetricCard
            icon={Infinity}
            label="Continuous collections"
            value={
              collectionCount === undefined || continuousCollectionCount === undefined
                ? "—"
                : `${formatNumber(continuousCollectionCount)}/${formatNumber(collectionCount)}`
            }
            detail={metricDetail(collectionsQuery, "Configured collections")}
          />
        </div>

        <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(20rem,0.85fr)]">
          <div className="grid min-w-0 gap-4">
            <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,0.95fr)]">
              <EditorialCommandCenter
                articles={articles}
                articleCount={articlesQuery.data?.resultCount}
                sourceCount={sourceCount}
                jobAttention={jobsQuery.data?.attention}
                collectionCount={collectionCount}
                timezone={timezone}
              />
              <LiveIngestionStatus query={viewOf(collectionsQuery)} timezone={timezone} />
            </div>

            <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.25fr)_minmax(0,1.05fr)]">
              <IssuesCard diagnostics={viewOf(diagnosticsQuery)} jobs={viewOf(jobsQuery)} />
              <RecentFeedCard
                articles={viewOf(articlesQuery)}
                timezone={timezone}
                onSelectArticle={setSelectedArticle}
              />
              <AutomationsCard query={viewOf(automationsQuery)} />
            </div>

            <IngestActivityCard query={viewOf(ingestRunsQuery)} timezone={timezone} />
          </div>

          <div className="grid min-w-0 content-start gap-4">
            <SystemHealthCard query={viewOf(diagnosticsQuery)} />
            <QueueStatusCard query={viewOf(diagnosticsQuery)} />
          </div>
        </div>
      </section>

      {selectedArticle ? (
        <ArticleDialog
          article={selectedArticle}
          timezone={timezone}
          onClose={() => setSelectedArticle(null)}
        />
      ) : null}
    </>
  )
}

function TodayHeader({ timezone }: { timezone: string }) {
  const [now, setNow] = useState<number | null>(null)

  useEffect(() => {
    const update = () => setNow(Date.now())
    update()
    const timer = window.setInterval(update, 1_000)
    return () => window.clearInterval(timer)
  }, [])

  const dateLabel = now === null
    ? "Current newsroom date"
    : formatInTimeZone(now, timezone, {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric",
      })
  const timeLabel = now === null
    ? "Current time unavailable"
    : formatInTimeZone(now, timezone, {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      })

  return (
    <header className="nc-page-header items-start" data-testid="today-header">
      <div>
        <h1 id="today-heading" className="nc-page-title text-3xl tracking-tight">Today</h1>
        <p className="nc-page-description">Your newsroom at a glance. {dateLabel}.</p>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="flex min-h-9 items-center gap-2 rounded-lg border border-border/70 bg-card px-3 py-2 text-xs shadow-sm">
          <Clock3 className="size-4 text-muted-foreground" aria-hidden="true" />
          <span className="font-medium">{timeLabel}</span>
          <span className="text-muted-foreground">{timezone}</span>
        </div>
        <Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/feed">
          Open Feed
          <ArrowUpRight aria-hidden="true" />
        </Link>
        <Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/operations">
          Operations
          <ArrowUpRight aria-hidden="true" />
        </Link>
      </div>
    </header>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: LucideIcon
  label: string
  value: string
  detail: ReactNode
}) {
  return (
    <Card className="min-w-0 flex-row items-center gap-3 p-3" size="sm">
      <span className="grid size-11 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-xs text-muted-foreground">{label}</p>
        <p className="mt-0.5 text-xl font-semibold tracking-tight">{value}</p>
        <p className="truncate text-[11px] text-muted-foreground">{detail}</p>
      </div>
    </Card>
  )
}

function EditorialCommandCenter({
  articles,
  articleCount,
  sourceCount,
  jobAttention,
  collectionCount,
  timezone,
}: {
  articles: ArticleSummary[]
  articleCount: number | undefined
  sourceCount: number | undefined
  jobAttention: number | undefined
  collectionCount: number | undefined
  timezone: string
}) {
  const topics = [...new Set(
    articles
      .map((article) => article.topic?.trim())
      .filter((topic): topic is string => Boolean(topic)),
  )].slice(0, 4)
  const summary = [
    articleCount === undefined ? null : `${formatNumber(articleCount)} article results available`,
    sourceCount === undefined ? null : `across ${formatNumber(sourceCount)} tracked sources`,
    jobAttention === undefined ? null : `${formatNumber(jobAttention)} jobs need attention`,
  ].filter(Boolean).join(", ")

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-primary" aria-hidden="true" />
          Editorial command center
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        <div className="flex min-w-0 items-start gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-6 text-muted-foreground">
              {summary || "Live newsroom metrics are not available yet."}
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
              <CommandMetric icon={FileText} value={metricValue(articleCount)} label="Article results" />
              <CommandMetric icon={Database} value={metricValue(sourceCount)} label="Tracked sources" />
              <CommandMetric icon={AlertTriangle} value={metricValue(jobAttention)} label="Jobs attention" />
              <CommandMetric icon={Gauge} value={metricValue(collectionCount)} label="Collections" />
            </div>
          </div>
          <ArticleHero article={articles[0]} />
        </div>
        {topics.length ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-border/50 pt-3">
            <span className="text-xs font-medium text-muted-foreground">Topics</span>
            {topics.map((topic) => <Badge key={topic} variant="secondary">{topic}</Badge>)}
          </div>
        ) : null}
        {articles[0] ? (
          <p className="text-xs text-muted-foreground">
            Latest result: {getArticleCardTime(articles[0].displayAt, articles[0].dateBasis, Date.now(), timezone).relativeLabel}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function CommandMetric({
  icon: Icon,
  value,
  label,
}: {
  icon: LucideIcon
  value: string
  label: string
}) {
  return (
    <div className="min-w-0">
      <Icon className="size-3.5 text-muted-foreground" aria-hidden="true" />
      <strong className="mt-1 block truncate text-sm">{value}</strong>
      <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{label}</span>
    </div>
  )
}

function ArticleHero({ article }: { article: ArticleSummary | undefined }) {
  if (!article?.image?.url) {
    return (
      <div className="hidden size-20 shrink-0 place-items-center rounded-lg border border-dashed border-border/70 bg-muted/40 text-muted-foreground sm:grid">
        <FileText className="size-6" aria-hidden="true" />
      </div>
    )
  }

  return (
    <img
      className="hidden size-20 shrink-0 rounded-lg border border-border/60 object-cover sm:block"
      src={article.image.url}
      alt={article.image.altText ?? article.title ?? "Article image"}
    />
  )
}

function LiveIngestionStatus({
  query,
  timezone,
}: {
  query: QueryView<SourceCollectionSummary[]>
  timezone: string
}) {
  const collections = query.data ?? []
  const activeRuns = collections.filter((collection) => collection.activeIngestRunId !== null).length
  const continuous = collections.filter((collection) => collection.continuousSubscriptionId !== null).length
  const nextCycle = collections.find((collection) => collection.continuousNextCycleAt)?.continuousNextCycleAt ?? null

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <RefreshCw className="size-4 text-primary" aria-hidden="true" />
            Live ingestion status
          </CardTitle>
          <Link className="text-xs font-medium text-primary hover:underline" href="/sources">Open Sources</Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        {query.isPending ? <LoadingState title="Loading ingestion collections…" className="min-h-24" /> : null}
        {query.isError ? <QueryError query={query} title="Ingestion status unavailable" retryLabel="Retry ingestion" /> : null}
        {!query.isPending && !query.isError ? (
          <>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-muted-foreground">Collections</span>
                <strong className="mt-1 block text-sm">{formatNumber(collections.length)}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Active runs</span>
                <strong className="mt-1 block text-sm">{formatNumber(activeRuns)}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Continuous</span>
                <strong className="mt-1 block text-sm">{formatNumber(continuous)}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Next cycle</span>
                <strong className="mt-1 block truncate text-sm">
                  {nextCycle ? formatInTimeZone(nextCycle, timezone, { hour: "numeric", minute: "2-digit" }) : "Not scheduled"}
                </strong>
              </div>
            </div>
            {collections.length ? (
              <div className="space-y-3">
                {collections.slice(0, 4).map((collection) => <CollectionRow key={collection.id} collection={collection} />)}
              </div>
            ) : (
              <EmptyState title="No source collections configured" description="Create a collection in Sources to monitor ingestion here." />
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}

function CollectionRow({ collection }: { collection: SourceCollectionSummary }) {
  const maximum = Math.max(collection.maximumSources, collection.sourceCount, 1)
  const progress = Math.min(100, Math.round((collection.sourceCount / maximum) * 100))
  const status = collection.activeIngestStatus ?? collection.continuousStatus ?? (
    collection.continuousSubscriptionId ? "configured" : "idle"
  )

  return (
    <div className="grid min-w-0 gap-1.5">
      <div className="flex min-w-0 items-center justify-between gap-3 text-xs">
        <span className="min-w-0 truncate font-medium">{collection.name}</span>
        <Badge variant={statusTone(status)}>{titleCase(status)}</Badge>
      </div>
      <div className="flex items-center gap-2">
        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted" aria-label={`${collection.sourceCount} of ${collection.maximumSources} sources`}>
          <span className="block h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${progress}%` }} />
        </div>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          {formatNumber(collection.sourceCount)} / {formatNumber(collection.maximumSources)}
        </span>
      </div>
    </div>
  )
}

function IssuesCard({
  diagnostics,
  jobs,
}: {
  diagnostics: QueryView<OperationsSnapshot>
  jobs: QueryView<{ attention: number; queued: number; running: number; succeeded_today: number }>
}) {
  const attention = diagnostics.data?.attention ?? []
  const jobAttention = jobs.data?.attention ?? 0

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Issues</CardTitle>
          <Link className="text-xs font-medium text-primary hover:underline" href="/operations">Open Operations</Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-3">
        {diagnostics.isPending ? <LoadingState title="Loading issues…" className="min-h-24" /> : null}
        {diagnostics.isError ? <QueryError query={diagnostics} title="Issues unavailable" retryLabel="Retry issues" /> : null}
        {!diagnostics.isPending && !diagnostics.isError && attention.length ? (
          <>
            {attention.slice(0, 4).map((item) => {
              const actionHref = internalHref(item.action_url)
              return (
                <div className="flex min-w-0 items-start gap-2 border-b border-border/50 pb-3 last:border-b-0 last:pb-0" key={item.id}>
                  <span className={cn(
                    "mt-0.5 grid size-7 shrink-0 place-items-center rounded-full",
                    item.severity === "error"
                      ? "bg-[var(--error-surface)] text-destructive"
                      : "bg-[var(--warning-surface)] text-warning",
                  )}>
                    <AlertTriangle className="size-3.5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{item.title}</p>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{titleCase(item.kind)}</p>
                    {actionHref ? <Link className="mt-1 inline-flex text-[11px] font-medium text-primary hover:underline" href={actionHref}>Inspect</Link> : null}
                  </div>
                  <Badge variant={item.severity === "error" ? "error" : "warning"}>{titleCase(item.severity)}</Badge>
                </div>
              )
            })}
            {attention.length > 4 ? <p className="text-xs text-muted-foreground">{formatNumber(attention.length - 4)} more attention items in Operations.</p> : null}
          </>
        ) : null}
        {!diagnostics.isPending && !diagnostics.isError && attention.length === 0 ? (
          jobAttention > 0 ? (
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 text-success" aria-hidden="true" />
              <p className="text-xs text-muted-foreground">
                Operations diagnostics reports no attention items; the job summary currently lists {formatNumber(jobAttention)} jobs needing attention.
              </p>
            </div>
          ) : (
            <EmptyState title="No active issues" description="Operations diagnostics reports no current attention items." />
          )
        ) : null}
      </CardContent>
    </Card>
  )
}

function RecentFeedCard({
  articles,
  timezone,
  onSelectArticle,
}: {
  articles: QueryView<{ items: ArticleSummary[]; nextCursor: string | null; resultCount: number }>
  timezone: string
  onSelectArticle: (article: ArticleSummary) => void
}) {
  const items = articles.data?.items ?? []

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Recent feed</CardTitle>
          <Link className="text-xs font-medium text-primary hover:underline" href="/feed">Open Feed</Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-1 pt-2">
        {articles.isPending ? <LoadingState title="Loading recent articles…" className="min-h-32" /> : null}
        {articles.isError ? <QueryError query={articles} title="Today stories unavailable" retryLabel="Retry Today" /> : null}
        {!articles.isPending && !articles.isError && items.length ? (
          items.slice(0, 5).map((article) => <ArticleRow key={article.id} article={article} timezone={timezone} onSelect={onSelectArticle} />)
        ) : null}
        {!articles.isPending && !articles.isError && items.length === 0 ? (
          <EmptyState title="No articles collected yet" description="NewsCraft will show source-grounded stories here after ingestion collects them." />
        ) : null}
      </CardContent>
    </Card>
  )
}

function ArticleRow({
  article,
  timezone,
  onSelect,
}: {
  article: ArticleSummary
  timezone: string
  onSelect: (article: ArticleSummary) => void
}) {
  const title = article.title?.trim() || "Untitled article"
  const time = getArticleCardTime(article.displayAt, article.dateBasis, Date.now(), timezone)

  return (
    <button
      className="flex w-full min-w-0 items-center gap-2 rounded-lg px-1.5 py-2 text-start transition-colors duration-150 hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/50 motion-reduce:transition-none"
      type="button"
      aria-label={`Open story: ${title}`}
      onClick={() => onSelect(article)}
    >
      {article.image?.url ? (
        <img className="size-9 shrink-0 rounded-md border border-border/60 object-cover" src={article.image.url} alt="" />
      ) : (
        <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
          <FileText className="size-4" aria-hidden="true" />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span role="heading" aria-level={3} className="block truncate text-xs font-medium">{title}</span>
        <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
          {article.source.name ?? article.domain ?? "Source unavailable"} · {time.relativeLabel}
        </span>
      </span>
      <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
    </button>
  )
}

function AutomationsCard({ query }: { query: QueryView<{ items: Automation[]; nextCursor: string | null }> }) {
  const automations = query.data?.items ?? []

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Automations</CardTitle>
          <Link className="text-xs font-medium text-primary hover:underline" href="/automations">Open Automations</Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-3">
        {query.isPending ? <LoadingState title="Loading automations…" className="min-h-24" /> : null}
        {query.isError ? <QueryError query={query} title="Automations unavailable" retryLabel="Retry automations" /> : null}
        {!query.isPending && !query.isError && automations.length ? automations.slice(0, 5).map((automation) => (
          <div className="flex min-w-0 items-start gap-2" key={automation.id}>
            <span className="grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
              <Workflow className="size-3.5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{automation.name}</p>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {automation.preview?.lastOutcome ?? automation.description ?? `Lifecycle: ${titleCase(automation.lifecycle)}`}
              </p>
            </div>
            <Badge variant={statusTone(automation.lifecycle)}>{titleCase(automation.lifecycle)}</Badge>
          </div>
        )) : null}
        {!query.isPending && !query.isError && automations.length === 0 ? (
          <EmptyState title="No automations configured" description="Create an automation to monitor it here." />
        ) : null}
      </CardContent>
    </Card>
  )
}

function IngestActivityCard({
  query,
  timezone,
}: {
  query: QueryView<IngestRunSummary[]>
  timezone: string
}) {
  const runs = query.data ?? []

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Activity className="size-4 text-primary" aria-hidden="true" />
            Ingestion activity
          </CardTitle>
          <Link className="text-xs font-medium text-primary hover:underline" href="/sources">Open Sources</Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 pt-3">
        {query.isPending ? <LoadingState title="Loading ingest runs…" className="min-h-28" /> : null}
        {query.isError ? <QueryError query={query} title="Ingestion activity unavailable" retryLabel="Retry ingest runs" /> : null}
        {!query.isPending && !query.isError && runs.length ? runs.map((run) => (
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-border/50 px-3 py-2.5" key={run.id}>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{run.sourceCollectionNameAtStart ?? "Ingest run"}</p>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {formatNumber(run.successCount)} succeeded · {formatNumber(run.failureCount)} failed · {titleCase(run.trigger)}
              </p>
            </div>
            <div className="flex items-end gap-2">
              <div className="text-end">
                <Badge variant={statusTone(run.status)}>{titleCase(run.status)}</Badge>
                <time className="mt-1 block text-[10px] text-muted-foreground" dateTime={run.startedAt} title={formatInTimeZone(run.startedAt, timezone)}>
                  {formatInTimeZone(run.startedAt, timezone, { dateStyle: "medium", timeStyle: "short" })}
                </time>
              </div>
            </div>
          </div>
        )) : null}
        {!query.isPending && !query.isError && runs.length === 0 ? (
          <EmptyState title="No ingest runs recorded" description="Completed and active collection runs will appear here." />
        ) : null}
      </CardContent>
    </Card>
  )
}

function SystemHealthCard({ query }: { query: QueryView<OperationsSnapshot> }) {
  const components = query.data ? Object.entries(query.data.components) : []

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Gauge className="size-4 text-primary" aria-hidden="true" />
            System health
          </CardTitle>
          <Link className="text-xs font-medium text-primary hover:underline" href="/operations">View details</Link>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-3">
        {query.isPending ? <LoadingState title="Loading system health…" className="min-h-24" /> : null}
        {query.isError ? <QueryError query={query} title="System health unavailable" retryLabel="Retry health" /> : null}
        {!query.isPending && !query.isError && components.length ? components.slice(0, 6).map(([name, component]) => (
          <div className="flex min-w-0 items-start gap-2" key={name}>
            <HealthIcon status={component.status} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{titleCase(name)}</p>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{component.message}</p>
            </div>
            <Badge variant={statusTone(component.status)}>{titleCase(component.status)}</Badge>
          </div>
        )) : null}
        {!query.isPending && !query.isError && components.length === 0 ? (
          <EmptyState title="No component health reported" description="Operations has not returned component status yet." />
        ) : null}
      </CardContent>
    </Card>
  )
}

function QueueStatusCard({ query }: { query: QueryView<OperationsSnapshot> }) {
  const queueEntries = query.data ? Object.entries(query.data.queue_counts).filter(([, count]) => typeof count === "number") : []

  return (
    <Card className="min-w-0">
      <CardHeader className="border-b border-border/50">
        <CardTitle className="flex items-center gap-2">
          <ListChecks className="size-4 text-primary" aria-hidden="true" />
          Queue status
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-3">
        {query.isPending ? <LoadingState title="Loading queue status…" className="min-h-24" /> : null}
        {query.isError ? <QueryError query={query} title="Queue status unavailable" retryLabel="Retry queue status" /> : null}
        {!query.isPending && !query.isError && queueEntries.length ? queueEntries.map(([name, count]) => (
          <div className="flex items-center justify-between gap-3 text-xs" key={name}>
            <span className="truncate text-muted-foreground">{titleCase(name)}</span>
            <strong>{formatNumber(count)}</strong>
          </div>
        )) : null}
        {!query.isPending && !query.isError && queueEntries.length === 0 ? (
          <EmptyState title="No queue counts reported" description="Operations has not returned queue metrics yet." />
        ) : null}
        {query.data ? (
          <div className="flex items-center gap-2 border-t border-border/50 pt-3 text-xs text-muted-foreground">
            <span className={cn("size-2 rounded-full", query.data.global_paused ? "bg-warning" : "bg-success")} aria-hidden="true" />
            {query.data.global_paused ? "Global processing is paused" : "Global processing is active"}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ArticleDialog({
  article,
  timezone,
  onClose,
}: {
  article: ArticleSummary
  timezone: string
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const title = article.title?.trim() || "Untitled article"
  const sourceUrl = safeHttpUrl(article.canonicalUrl)
  const summary = article.summary?.trim() || article.excerpt?.trim() || "Full article text is not available in the Today summary."
  const time = getArticleCardTime(article.displayAt, article.dateBasis, Date.now(), timezone)

  useEditorialModal({ open: true, containerRef: dialogRef, initialFocusRef: closeRef, onClose })

  return (
    <>
      <div className="fixed inset-0 z-50 cursor-pointer bg-foreground/45 backdrop-blur-sm" aria-hidden="true" onPointerDown={onClose} />
      <section className="fixed left-1/2 top-1/2 z-50 w-[min(680px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card text-card-foreground shadow-2xl" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="today-article-dialog-title" tabIndex={-1}>
        <Button className="absolute right-3 top-3" variant="ghost" size="icon" aria-label="Close story" onClick={onClose} ref={closeRef} type="button">
          <X aria-hidden="true" />
        </Button>
        <div className="space-y-4 p-6 sm:p-8">
          <p className="text-xs text-muted-foreground">{article.source.name ?? article.domain ?? "NewsCraft"} · {time.relativeLabel}</p>
          <h2 id="today-article-dialog-title" className="max-w-[28ch] text-2xl font-semibold leading-tight">{title}</h2>
          {sourceUrl ? <a className="inline-flex text-sm font-medium text-primary hover:underline" href={sourceUrl} target="_blank" rel="noreferrer noopener">Open original at {article.source.name ?? "source"}</a> : null}
          <p className="text-sm leading-7 text-muted-foreground">{summary}</p>
        </div>
      </section>
    </>
  )
}

function QueryError<T>({
  query,
  title,
  retryLabel,
}: {
  query: QueryView<T>
  title: string
  retryLabel: string
}) {
  return (
    <ErrorState
      title={title}
      description={getApiErrorMessage(query.error, "The live NewsCraft data source could not be reached.")}
      action={<Button variant="outline" size="sm" onClick={query.retry}>{retryLabel}</Button>}
    />
  )
}

function HealthIcon({ status }: { status: string }) {
  if (status === "healthy") return <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />
  if (status === "degraded") return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
  return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
}

function metricValue(value: number | undefined) {
  return value === undefined ? "—" : formatNumber(value)
}

function metricDetail<T>(query: QueryView<T> | QueryLike<T>, label: string) {
  if (query.isPending) return "Loading…"
  if (query.isError) return "Unavailable"
  return label
}

function viewOf<T>(query: QueryLike<T>): QueryView<T> {
  return {
    data: query.data,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error,
    retry: () => { void query.refetch() },
  }
}

function statusTone(status: string): "success" | "warning" | "error" | "neutral" {
  const normalized = status.toLowerCase()
  if (["healthy", "active", "running", "succeeded", "success", "completed", "complete", "ready"].includes(normalized)) return "success"
  if (["degraded", "paused", "queued", "pending", "warning", "configured"].includes(normalized)) return "warning"
  if (["down", "failed", "error", "cancelled", "canceled"].includes(normalized)) return "error"
  return "neutral"
}

function internalHref(value: string | null | undefined) {
  return value?.startsWith("/") ? value : null
}

