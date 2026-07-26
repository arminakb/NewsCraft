import { enqueueIngest } from "@/features/jobs/api"
import { titleCase } from "@/lib/format"
import { apiRequest } from "@/lib/http"
import type { components } from "@/lib/api/generated"

import type {
  IngestionRunSummary,
  SourcePlatform,
  SourceStatus,
  SourceSummary,
} from "./ingestion-types"

type BackendSource =
  | components["schemas"]["SourceOut"]
  | components["schemas"]["SourceDetailOut"]
type BackendRun = components["schemas"]["IngestRunSummaryOut"]

export async function getSources(): Promise<SourceSummary[]> {
  const rows = await apiRequest<BackendSource[]>("/sources")
  return rows.map(mapSource)
}

export async function getSource(id: string): Promise<SourceSummary> {
  const row = await apiRequest<BackendSource>(`/sources/${encodeURIComponent(id)}`)
  return mapSource(row)
}

export function seedSources(): Promise<{ upserted: number }> {
  return apiRequest("/sources/seed", { method: "POST" })
}

export function runIngest(input: {
  platforms?: string[]
  sourceIds?: string[]
}) {
  return enqueueIngest({
    requestId: crypto.randomUUID(),
    platforms: input.platforms,
    sourceIds: input.sourceIds,
  })
}

export async function getIngestRuns(): Promise<IngestionRunSummary[]> {
  const rows = await apiRequest<BackendRun[]>("/ingest/runs")
  return rows.map(mapRun)
}

function mapSource(row: BackendSource): SourceSummary {
  const platform = normalizePlatform(row.platform)
  const url =
    row.feed_url ??
    row.homepage_url ??
    (row.telegram_username ? `https://t.me/${row.telegram_username}` : "")
  const status = normalizeSourceStatus(row.health_status, row.active, row.failure_count ?? 0)
  const lastSuccess = row.last_success_at
    ? formatDateTime(row.last_success_at)
    : row.last_fetch_at
      ? formatDateTime(row.last_fetch_at)
      : null

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
    fetchIntervalMinutes: row.fetch_interval_minutes ?? 1440,
    totalItems: row.last_parse_count ?? 0,
    media24h: row.last_media_count ?? 0,
    addedAt: row.created_at ? formatDateTime(row.created_at) : "Unknown",
  }
}

function mapRun(row: BackendRun): IngestionRunSummary {
  const stats = row.stats ?? {}
  const items = typeof stats.items === "number" ? stats.items : 0
  const checked = typeof stats.checked === "number" ? stats.checked : items

  return {
    id: row.id,
    label: formatDateTime(row.started_at),
    scope: titleCase(row.trigger || "All sources"),
    status:
      row.status === "failed"
        ? "failed"
        : row.status === "partial"
          ? "partial"
          : "succeeded",
    progress:
      checked > 0
        ? Math.min(100, Math.round((items / checked) * 100))
        : row.status === "failed"
          ? 0
          : 100,
    duration: formatDuration(row.started_at, row.finished_at),
    items,
  }
}

function normalizePlatform(platform: string): SourcePlatform {
  switch (platform) {
    case "rss":
    case "atom":
    case "telegram_public":
    case "google_news":
    case "gdelt":
    case "hackernews":
      return platform
    default:
      return "unknown"
  }
}

function normalizeSourceStatus(
  status: string | null | undefined,
  active = true,
  failureCount = 0,
): SourceStatus {
  if (!active) return "disabled"
  switch (status) {
    case "healthy":
    case "degraded":
    case "broken":
    case "disabled":
    case "unknown":
      return status
    case "partial":
      return "degraded"
    case "failed":
    case "unhealthy":
      return "broken"
    default:
      if (failureCount >= 5) return "broken"
      if (failureCount > 0) return "degraded"
      return "unknown"
  }
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

function formatDuration(start: string, end?: string | null) {
  if (!end) return "00:00"
  const seconds = Math.max(
    0,
    Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000),
  )
  const minutes = Math.floor(seconds / 60)
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`
}
