import { titleCase } from "@/lib/format"
import { apiRequest, apiRequestVoid } from "@/lib/http"
import type { components } from "@/lib/api/generated"

import type {
  CreateSourceInput,
  SourcePlatform,
  SourceHealthResult,
  SourceStatus,
  SourceSummary,
} from "./ingestion-types"

type BackendSource =
  | components["schemas"]["SourceOut"]
  | components["schemas"]["SourceDetailOut"]
type BackendSourceHealth = components["schemas"]["SourceHealthOut"]

export async function getSources(signal?: AbortSignal): Promise<SourceSummary[]> {
  const rows = await apiRequest<BackendSource[]>("/sources", signal ? { signal } : undefined)
  return rows.map(mapSource)
}

export async function getSource(id: string): Promise<SourceSummary> {
  const row = await apiRequest<BackendSource>(`/sources/${encodeURIComponent(id)}`)
  return mapSource(row)
}

export async function createSource(input: CreateSourceInput): Promise<SourceSummary> {
  const row = await apiRequest<BackendSource>("/sources", {
    method: "POST",
    body: JSON.stringify({
      platform: input.platform,
      name: input.name,
      url: input.url,
      source_group: input.category,
      language_hint: input.language,
      fetch_interval_minutes: input.fetchIntervalMinutes,
    }),
  })
  return mapSource(row)
}

export function deleteSource(id: string): Promise<void> {
  return apiRequestVoid(`/sources/${encodeURIComponent(id)}`, { method: "DELETE" })
}

export async function checkSourceHealth(id: string): Promise<SourceHealthResult> {
  const row = await apiRequest<BackendSourceHealth>(
    `/sources/${encodeURIComponent(id)}/health-check`,
    { method: "POST" },
  )
  return {
    sourceId: row.source_id,
    status: normalizeSourceStatus(row.health_status),
    isChecking: row.is_checking,
    lastCheckedAt: row.last_checked_at,
    failureReason: row.failure_reason ?? null,
  }
}

export function seedSources(): Promise<{ upserted: number }> {
  return apiRequest("/sources/seed", { method: "POST" })
}

function mapSource(row: BackendSource): SourceSummary {
  const platform = normalizePlatform(row.platform)
  const url =
    row.feed_url ??
    row.homepage_url ??
    (row.telegram_username ? `https://t.me/${row.telegram_username}` : "")
  const status = normalizeSourceStatus(row.health_status, row.active, row.failure_count ?? 0)
  const lastSuccess = row.last_success_at
    ? row.last_success_at
    : row.last_fetch_at
      ? row.last_fetch_at
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
    addedAt: row.created_at ?? "Unknown",
    lastCheckedAt: row.last_fetch_at ?? null,
    failureReason: row.last_error_message ?? null,
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
