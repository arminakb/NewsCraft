import { dashboardMock } from "./mock-data"
import type {
  ContentQueueItem,
  DashboardCounts,
  DashboardSnapshot,
  DiagnosticsSnapshot,
  IngestionRunSummary,
  MediaTile,
  SourcePlatform,
  SourceStatus,
  SourceSummary,
} from "./types"
import { formatBytes, formatPlatform, titleCase } from "./format"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend"

type BackendSource = {
  id: string
  platform: string
  name: string
  feed_url?: string | null
  homepage_url?: string | null
  telegram_username?: string | null
  source_group?: string | null
  language_hint?: string | null
  active?: boolean
  last_fetch_at?: string | null
  last_success_at?: string | null
  last_failure_at?: string | null
  failure_count?: number
  health_status?: string | null
  last_parse_count?: number
  last_suitable_count?: number
  last_media_count?: number
  fetch_interval_minutes?: number
  created_at?: string | null
}

type BackendContentItem = {
  id: string
  item_type?: string | null
  title?: string | null
  summary?: string | null
  canonical_url?: string | null
  language_code?: string | null
  status: string
  score?: number
  tags?: string[]
  sort_at?: string
  primary_media?: {
    normalized_url?: string | null
    media_quality?: string | null
    fetch_status?: string | null
  } | null
  metrics?: Record<string, unknown>
  content_type?: string | null
  rewrite_bucket?: string | null
  is_rewrite_ready?: boolean | null
  rewrite_ready_reason?: string | null
  rewrite_blockers?: string[]
  classification_reasons?: string[]
  source_tier?: string | null
  freshness_bucket?: string | null
  quality_status?: string | null
  score_breakdown?: Record<string, unknown>
}

type BackendMediaAsset = {
  id: string
  normalized_url: string
  kind: string
  mime_type?: string | null
  width?: number | null
  height?: number | null
  storage_path?: string | null
  byte_length?: number | null
  created_at?: string | null
}

type BackendRun = {
  id: string
  started_at: string
  finished_at?: string | null
  status: string
  trigger: string
  stats?: Record<string, unknown>
}

type BackendDashboardSummary = {
  rss_feeds: number
  telegram_channels: number
  content_items: number
  media_assets: number
  warnings: number
}

type BackendDiagnostics = {
  status: string
  checks: Record<string, string>
  source_health: Record<string, number>
  problem_sources: Array<Record<string, unknown>>
}

type ContentItemFilters = {
  status?: string
  contentType?: string
  rewriteBucket?: string
  isRewriteReady?: boolean
  sourceTier?: string
  qualityStatus?: string
  sort?: "latest" | "score"
  limit?: number
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export async function getSources(): Promise<SourceSummary[]> {
  const rows = await request<BackendSource[]>("/sources")
  return rows.map(mapSource)
}

export async function getDashboardSummary(): Promise<DashboardCounts> {
  const row = await request<BackendDashboardSummary>("/dashboard/summary")
  return {
    rssFeeds: row.rss_feeds,
    telegramChannels: row.telegram_channels,
    contentItems: row.content_items,
    mediaAssets: row.media_assets,
    warnings: row.warnings,
  }
}

export async function seedSources(): Promise<{ upserted: number }> {
  return request("/sources/seed", { method: "POST" })
}

export async function getDiagnostics(): Promise<DiagnosticsSnapshot> {
  const row = await request<BackendDiagnostics>("/diagnostics")
  return {
    status: row.status,
    checks: row.checks,
    sourceHealth: row.source_health,
    problemSources: row.problem_sources,
  }
}

export async function runIngest(input: { platforms?: string[]; source_ids?: string[] }) {
  return request("/ingest/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  })
}

export async function approveContentItem(id: string, input: { notes?: string | null }) {
  return request(`/content-items/${id}/approve`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  })
}

export async function getContentItems(filters: ContentItemFilters = {}): Promise<ContentQueueItem[]> {
  const params = new URLSearchParams()
  params.set("limit", String(filters.limit ?? 50))
  if (filters.status) params.set("status", filters.status)
  if (filters.contentType) params.set("content_type", filters.contentType)
  if (filters.rewriteBucket) params.set("rewrite_bucket", filters.rewriteBucket)
  if (filters.isRewriteReady !== undefined) params.set("is_rewrite_ready", String(filters.isRewriteReady))
  if (filters.sourceTier) params.set("source_tier", filters.sourceTier)
  if (filters.qualityStatus) params.set("quality_status", filters.qualityStatus)
  if (filters.sort) params.set("sort", filters.sort)

  const rows = await request<BackendContentItem[]>(`/content-items?${params.toString()}`)
  return rows.map(mapContentItem)
}

export async function getIngestRuns(): Promise<IngestionRunSummary[]> {
  const rows = await request<BackendRun[]>("/ingest/runs")
  return rows.map(mapRun)
}

export async function getMediaAssets(): Promise<MediaTile[]> {
  const rows = await request<BackendMediaAsset[]>("/media-assets")
  return rows.slice(0, 12).map(mapMedia)
}

export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  const [counts, sources, queue, runs, media] = await Promise.all([
    getDashboardSummary(),
    getSources(),
    getContentItems(),
    getIngestRuns().catch(() => dashboardMock.runs),
    getMediaAssets().catch(() => dashboardMock.media),
  ])

  return {
    counts,
    sources,
    runs,
    queue,
    media,
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) {
    throw new ApiError(response.statusText || "Request failed", response.status, await response.text())
  }
  return response.json() as Promise<T>
}

function mapSource(row: BackendSource): SourceSummary {
  const platform = normalizePlatform(row.platform)
  const url = row.feed_url ?? row.homepage_url ?? (row.telegram_username ? `https://t.me/${row.telegram_username}` : "")
  const status = normalizeSourceStatus(row.health_status, row.active, row.failure_count)
  const lastSuccess = row.last_success_at ? formatTime(row.last_success_at) : row.last_fetch_at ? formatTime(row.last_fetch_at) : null
  const interval = row.fetch_interval_minutes ?? 30

  return {
    id: row.id,
    platform,
    name: row.name,
    url,
    category: titleCase(row.source_group ?? "General"),
    language: row.language_hint ?? "en",
    status,
    items24h: row.last_parse_count ?? 0,
    new24h: row.last_suitable_count ?? 0,
    failed24h: row.failure_count ?? 0,
    lastSuccess,
    nextRun: row.active === false ? null : `in ${interval}m`,
    totalItems: row.last_parse_count ?? 0,
    media24h: row.last_media_count ?? 0,
    addedAt: row.created_at ? formatDateTime(row.created_at) : "Unknown",
    parser: platform === "rss" ? "RSS 2.0" : "Telegram public HTML",
    deduplication: platform === "rss" ? "URL + GUID" : "Message ID + URL",
  }
}

function mapContentItem(row: BackendContentItem): ContentQueueItem {
  const metrics = row.metrics ?? {}
  const classification = typeof metrics.classification === "object" && metrics.classification ? metrics.classification : {}
  const category = "category" in classification ? String(classification.category) : titleCase(row.source_tier ?? "AI")

  return {
    id: row.id,
    title: row.title ?? "Untitled content item",
    summary: row.summary ?? null,
    canonicalUrl: row.canonical_url ?? null,
    thumbnailUrl: row.primary_media?.normalized_url ?? null,
    primaryMedia: row.primary_media
      ? {
          src: row.primary_media.normalized_url ?? null,
          quality: row.primary_media.media_quality ?? null,
          fetchStatus: row.primary_media.fetch_status ?? null,
        }
      : null,
    sourceName: "NewsCraft",
    sourcePlatform: "rss",
    category,
    language: row.language_code ?? "en",
    age: row.sort_at ? formatRelativeAge(row.sort_at) : "now",
    status: row.status,
    score: row.score ?? 0,
    tags: row.tags ?? [],
    contentType: row.content_type ?? row.item_type ?? null,
    rewriteBucket: row.rewrite_bucket ?? null,
    isRewriteReady: row.is_rewrite_ready ?? null,
    rewriteReadyReason: row.rewrite_ready_reason ?? null,
    rewriteBlockers: row.rewrite_blockers ?? [],
    classificationReasons: row.classification_reasons ?? [],
    sourceTier: row.source_tier ?? null,
    freshnessBucket: row.freshness_bucket ?? null,
    qualityStatus: row.quality_status ?? null,
    scoreBreakdown: row.score_breakdown ?? {},
  }
}

function mapRun(row: BackendRun): IngestionRunSummary {
  const stats = row.stats ?? {}
  const items = typeof stats.items === "number" ? stats.items : 0
  const checked = typeof stats.checked === "number" ? stats.checked : items

  return {
    id: row.id,
    label: formatRunLabel(row.started_at),
    scope: titleCase(row.trigger || "All sources"),
    status: row.status === "failed" ? "failed" : row.status === "partial" ? "partial" : "succeeded",
    progress: checked > 0 ? Math.min(100, Math.round((items / checked) * 100)) : row.status === "failed" ? 0 : 100,
    duration: formatDuration(row.started_at, row.finished_at),
    items,
  }
}

function mapMedia(row: BackendMediaAsset): MediaTile {
  const format = row.mime_type?.split("/").pop()?.toUpperCase() ?? row.kind.toUpperCase()
  return {
    id: row.id,
    src: row.normalized_url,
    format,
    dimensions: row.width && row.height ? `${row.width}x${row.height}` : "unknown",
    fileName: row.storage_path?.split("/").pop() ?? row.normalized_url.split("/").pop() ?? "media",
    age: row.created_at ? `${formatRelativeAge(row.created_at)} ago` : "now",
    size: formatBytes(row.byte_length),
  }
}

function normalizePlatform(platform: string): SourcePlatform {
  return platform === "telegram_public" ? "telegram_public" : "rss"
}

function normalizeSourceStatus(status: string | null | undefined, active = true, failureCount = 0): SourceStatus {
  if (!active || status === "failed" || status === "unhealthy" || failureCount >= 5) {
    return "failed"
  }
  if (status === "partial" || failureCount > 0) {
    return "partial"
  }
  return "healthy"
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value))
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(new Date(value))
    .replace(",", "")
}

function formatRunLabel(value: string) {
  return `Today ${formatTime(value)}`
}

function formatDuration(start: string, end?: string | null) {
  if (!end) {
    return "00:00"
  }
  const seconds = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000))
  const minutes = Math.floor(seconds / 60)
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`
}

function formatRelativeAge(value: string) {
  const diffMinutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000))
  if (diffMinutes < 60) {
    return `${diffMinutes}m`
  }
  return `${Math.round(diffMinutes / 60)}h`
}

export { API_BASE_URL, formatPlatform }
