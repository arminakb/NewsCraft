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
type BackendSourcePage = {
  items: BackendSource[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export type SourcePageFilters = {
  search?: string
  platform?: string
  sourceGroup?: string
  collectionId?: string
  unassigned?: boolean
  excludeCollectionId?: string
  limit?: number
  offset?: number
}

export type SourcePage = {
  items: SourceSummary[]
  total: number
  limit: number
  offset: number
  hasMore: boolean
}

export type SourceSummaryList = SourceSummary[] & {
  total: number
  limit: number
  offset: number
  hasMore: boolean
}

export type SourceCollectionSummary = {
  id: string
  name: string
  description: string | null
  sourceCount: number
  maximumSources: number
  createdAt: string
  updatedAt: string
  activeIngestRunId: string | null
  activeIngestStatus: string | null
  activeIngestSourceCount: number | null
  activeIngestProcessedCount: number | null
  activeIngestSuccessCount: number | null
  activeIngestFailureCount: number | null
  continuousSubscriptionId: string | null
  continuousMode: "continuous" | null
  continuousStatus: string | null
  continuousIntervalMinutes: number | null
  continuousStartedAt: string | null
  continuousStoppedAt: string | null
  continuousLastCycleAt: string | null
  continuousNextCycleAt: string | null
  continuousLastSuccessAt: string | null
  continuousCycleCount: number | null
  continuousLastCycleStatus: string | null
  continuousLastError: string | null
  continuousCurrentCycleJobId: string | null
  continuousCurrentCycleRunId: string | null
}

export type SourceCollectionIngestMode = "once" | "continuous"

export type SourceCollectionSubscription = {
  id: string
  sourceCollectionId: string | null
  sourceCollectionName: string | null
  mode: "continuous"
  status: string
  createdAt: string
  startedAt: string | null
  stoppedAt: string | null
  lastCycleAt: string | null
  nextCycleAt: string | null
  lastSuccessAt: string | null
  cycleCount: number
  intervalMinutes: number
  createdBy: string
  lastCycleStatus: string | null
  lastError: string | null
  currentCycleJobId: string | null
  currentCycleRunId: string | null
}

export type SourceCollectionMembershipChange = {
  collectionId: string
  addedSourceIds: string[]
  removedSourceIds: string[]
  alreadyMemberSourceIds: string[]
  missingSourceIds: string[]
  sourceCount: number
  maximumSources: number
}

export type SourceCollectionIngestAccepted = {
  jobId: string | null
  runId: string | null
  sourceCollectionId: string
  sourceCollectionName: string
  sourceCount: number
  status: string
  deduplicated: boolean
  mode: SourceCollectionIngestMode
  subscriptionId: string | null
  intervalMinutes: number | null
  nextCycleAt: string | null
}

export type SourceCollectionRunSource = {
  id: string
  sourceId: string | null
  position: number
  sourceName: string
  platform: string
  status: string
  startedAt: string | null
  completedAt: string | null
  error: string | null
}

export type SourceCollectionRun = {
  id: string
  sourceCollectionId: string | null
  sourceCollectionNameAtStart: string | null
  sourceCount: number
  processedCount: number
  successCount: number
  failureCount: number
  startedAt: string
  completedAt: string | null
  status: string
  trigger: string
  mode: SourceCollectionIngestMode
  continuousSubscriptionId: string | null
  continuousCycleNumber: number | null
  error: string | null
  sources: SourceCollectionRunSource[]
}

export type SourceCollectionRunPage = {
  items: SourceCollectionRun[]
  total: number
  limit: number
  offset: number
  hasMore: boolean
}

export type IngestRunSummary = {
  id: string
  startedAt: string
  finishedAt: string | null
  trigger: string
  status: string
  stats: Record<string, unknown>
  sourceCollectionId: string | null
  sourceCollectionNameAtStart: string | null
  sourceCount: number
  processedCount: number
  successCount: number
  failureCount: number
}

export async function getSources(signal?: AbortSignal): Promise<SourceSummaryList>
export async function getSources(filters?: SourcePageFilters, signal?: AbortSignal): Promise<SourceSummaryList>
export async function getSources(
  filtersOrSignal: SourcePageFilters | AbortSignal = {},
  signal?: AbortSignal,
): Promise<SourceSummaryList> {
  const filters = isAbortSignal(filtersOrSignal) ? {} : filtersOrSignal
  const requestSignal = isAbortSignal(filtersOrSignal) ? filtersOrSignal : signal
  const page = await getSourcePage(filters, requestSignal)
  const rows = page.items as SourceSummaryList
  Object.defineProperties(rows, {
    total: { value: page.total, enumerable: false },
    limit: { value: page.limit, enumerable: false },
    offset: { value: page.offset, enumerable: false },
    hasMore: { value: page.hasMore, enumerable: false },
  })
  return rows
}

export async function getSourcePage(
  filters: SourcePageFilters = {},
  signal?: AbortSignal,
): Promise<SourcePage> {
  const query = buildSourceQuery(filters)
  const payload = await apiRequest<BackendSourcePage | BackendSource[]>(
    `/sources/search${query}`,
    signal ? { signal } : undefined,
  )
  if (Array.isArray(payload)) {
    const items = payload.map(mapSource)
    return { items, total: items.length, limit: items.length || 1, offset: 0, hasMore: false }
  }
  return {
    items: payload.items.map(mapSource),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    hasMore: payload.has_more,
  }
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

export function reportSourceIconFailure(id: string): Promise<void> {
  return apiRequestVoid(`/sources/${encodeURIComponent(id)}/icon-failure`, { method: "POST" })
}

export function seedSources(): Promise<{ upserted: number }> {
  return apiRequest("/sources/seed", { method: "POST" })
}

export async function getSourceCollections(signal?: AbortSignal): Promise<SourceCollectionSummary[]> {
  const rows = await apiRequest<BackendSourceCollection[]>(
    "/source-collections",
    signal ? { signal } : undefined,
  )
  return rows.map(mapSourceCollection)
}

export async function getIngestRuns(limit = 6, signal?: AbortSignal): Promise<IngestRunSummary[]> {
  const boundedLimit = Math.min(Math.max(Math.trunc(limit), 1), 25)
  const rows = await apiRequest<components["schemas"]["IngestRunSummaryOut"][]>(
    `/ingest/runs?limit=${boundedLimit}`,
    signal ? { signal } : undefined,
  )
  return rows.map((row) => ({
    id: row.id,
    startedAt: row.started_at,
    finishedAt: row.finished_at ?? null,
    trigger: row.trigger,
    status: row.status,
    stats: row.stats ?? {},
    sourceCollectionId: row.source_collection_id ?? null,
    sourceCollectionNameAtStart: row.source_collection_name_at_start ?? null,
    sourceCount: row.source_count,
    processedCount: row.processed_count,
    successCount: row.success_count,
    failureCount: row.failure_count,
  }))
}

export async function createSourceCollection(input: {
  name: string
  description?: string | null
}): Promise<SourceCollectionSummary> {
  const description = input.description?.trim()
  const body = {
    name: input.name.trim(),
    ...(description ? { description } : {}),
  } satisfies components["schemas"]["SourceCollectionCreateIn"]
  const row = await apiRequest<BackendSourceCollection>("/source-collections", {
    ...jsonRequest("POST", body),
  })
  return mapSourceCollection(row)
}

export async function updateSourceCollection(
  id: string,
  input: { name?: string; description?: string | null },
): Promise<SourceCollectionSummary> {
  const body = {
    ...(input.name === undefined ? {} : { name: input.name.trim() }),
    ...(input.description === undefined
      ? {}
      : { description: input.description === null ? null : input.description.trim() || null }),
  } satisfies components["schemas"]["SourceCollectionUpdateIn"]
  const row = await apiRequest<BackendSourceCollection>(
    `/source-collections/${encodeURIComponent(id)}`,
    jsonRequest("PATCH", body),
  )
  return mapSourceCollection(row)
}

export function deleteSourceCollection(id: string): Promise<void> {
  return apiRequestVoid(`/source-collections/${encodeURIComponent(id)}`, { method: "DELETE" })
}

export async function getSourceCollectionSources(
  id: string,
  filters: Omit<SourcePageFilters, "collectionId" | "unassigned" | "excludeCollectionId"> = {},
  signal?: AbortSignal,
): Promise<SourcePage> {
  const query = buildSourceQuery(filters)
  const payload = await apiRequest<BackendSourcePage>(
    `/source-collections/${encodeURIComponent(id)}/sources${query}`,
    signal ? { signal } : undefined,
  )
  return mapSourcePage(payload)
}

export async function getUnassignedSources(
  filters: Omit<SourcePageFilters, "collectionId" | "unassigned" | "excludeCollectionId"> = {},
  signal?: AbortSignal,
): Promise<SourcePage> {
  const query = buildSourceQuery(filters)
  const payload = await apiRequest<BackendSourcePage>(
    `/source-collections/unassigned/sources${query}`,
    signal ? { signal } : undefined,
  )
  return mapSourcePage(payload)
}

export async function addSourcesToCollection(
  collectionId: string,
  sourceIds: string[],
): Promise<SourceCollectionMembershipChange> {
  const payload = await apiRequest<BackendSourceCollectionMembershipChange>(
    `/source-collections/${encodeURIComponent(collectionId)}/sources`,
    jsonRequest("POST", { source_ids: sourceIds }),
  )
  return mapMembershipChange(payload)
}

export async function removeSourcesFromCollection(
  collectionId: string,
  sourceIds: string[],
): Promise<SourceCollectionMembershipChange> {
  const payload = await apiRequest<BackendSourceCollectionMembershipChange>(
    `/source-collections/${encodeURIComponent(collectionId)}/sources`,
    jsonRequest("DELETE", { source_ids: sourceIds }),
  )
  return mapMembershipChange(payload)
}

export async function startSourceCollectionIngest(
  collectionId: string,
  requestId: string,
  mode: SourceCollectionIngestMode = "once",
): Promise<SourceCollectionIngestAccepted> {
  const payload = await apiRequest<{
    job_id: string | null
    run_id: string | null
    source_collection_id: string
    source_collection_name: string
    source_count: number
    status: string
    deduplicated: boolean
    mode?: SourceCollectionIngestMode
    subscription_id?: string | null
    interval_minutes?: number | null
    next_cycle_at?: string | null
  }>(
    `/source-collections/${encodeURIComponent(collectionId)}/ingest`,
    jsonRequest("POST", { mode, request_id: requestId }),
  )
  return {
    jobId: payload.job_id,
    runId: payload.run_id,
    sourceCollectionId: payload.source_collection_id,
    sourceCollectionName: payload.source_collection_name,
    sourceCount: payload.source_count,
    status: payload.status,
    deduplicated: payload.deduplicated,
    mode: payload.mode ?? mode,
    subscriptionId: payload.subscription_id ?? null,
    intervalMinutes: payload.interval_minutes ?? null,
    nextCycleAt: payload.next_cycle_at ?? null,
  }
}

export async function getSourceCollectionContinuous(
  collectionId: string,
  signal?: AbortSignal,
): Promise<SourceCollectionSubscription> {
  const payload = await apiRequest<BackendSourceCollectionSubscription>(
    `/source-collections/${encodeURIComponent(collectionId)}/continuous`,
    signal ? { signal } : undefined,
  )
  return mapSourceCollectionSubscription(payload)
}

export async function stopSourceCollectionContinuous(
  collectionId: string,
): Promise<SourceCollectionSubscription> {
  const payload = await apiRequest<BackendSourceCollectionSubscription>(
    `/source-collections/${encodeURIComponent(collectionId)}/continuous/stop`,
    jsonRequest("POST", {}),
  )
  return mapSourceCollectionSubscription(payload)
}

export async function getSourceCollectionRun(
  collectionId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<SourceCollectionRun> {
  const payload = await apiRequest<BackendSourceCollectionRun>(
    `/source-collections/${encodeURIComponent(collectionId)}/runs/${encodeURIComponent(runId)}`,
    signal ? { signal } : undefined,
  )
  return mapSourceCollectionRun(payload)
}

export async function getSourceCollectionRuns(
  collectionId: string,
  limit = 10,
  signal?: AbortSignal,
): Promise<SourceCollectionRunPage> {
  const payload = await apiRequest<BackendSourceCollectionRunPage>(
    `/source-collections/${encodeURIComponent(collectionId)}/runs?limit=${limit}&offset=0`,
    signal ? { signal } : undefined,
  )
  return {
    items: payload.items.map(mapSourceCollectionRun),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    hasMore: payload.has_more,
  }
}

type BackendSourceCollection = {
  id: string
  name: string
  description: string | null
  source_count: number
  maximum_sources: number
  created_at: string
  updated_at: string
  active_ingest_run_id: string | null
  active_ingest_status: string | null
  active_ingest_source_count: number | null
  active_ingest_processed_count: number | null
  active_ingest_success_count: number | null
  active_ingest_failure_count: number | null
  continuous_subscription_id?: string | null
  continuous_mode?: "continuous" | null
  continuous_status?: string | null
  continuous_interval_minutes?: number | null
  continuous_started_at?: string | null
  continuous_stopped_at?: string | null
  continuous_last_cycle_at?: string | null
  continuous_next_cycle_at?: string | null
  continuous_last_success_at?: string | null
  continuous_cycle_count?: number | null
  continuous_last_cycle_status?: string | null
  continuous_last_error?: string | null
  continuous_current_cycle_job_id?: string | null
  continuous_current_cycle_run_id?: string | null
}

type BackendSourceCollectionSubscription = {
  id: string
  source_collection_id: string | null
  source_collection_name: string | null
  mode: "continuous"
  status: string
  created_at: string
  started_at: string | null
  stopped_at: string | null
  last_cycle_at: string | null
  next_cycle_at: string | null
  last_success_at: string | null
  cycle_count: number
  interval_minutes: number
  created_by: string
  last_cycle_status: string | null
  last_error: string | null
  current_cycle_job_id: string | null
  current_cycle_run_id: string | null
}

type BackendSourceCollectionMembershipChange = {
  collection_id: string
  added_source_ids: string[]
  removed_source_ids: string[]
  already_member_source_ids: string[]
  missing_source_ids: string[]
  source_count: number
  maximum_sources: number
}

type BackendSourceCollectionRun = {
  id: string
  source_collection_id: string | null
  source_collection_name_at_start: string | null
  source_count: number
  processed_count: number
  success_count: number
  failure_count: number
  started_at: string
  completed_at: string | null
  status: string
  trigger: string
  mode?: SourceCollectionIngestMode
  continuous_subscription_id?: string | null
  continuous_cycle_number?: number | null
  error: string | null
  sources: Array<{
    id: string
    source_id: string | null
    position: number
    source_name: string
    platform: string
    status: string
    started_at: string | null
    completed_at: string | null
    error: string | null
  }>
}

type BackendSourceCollectionRunPage = {
  items: BackendSourceCollectionRun[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

function mapSourcePage(payload: BackendSourcePage): SourcePage {
  return {
    items: payload.items.map(mapSource),
    total: payload.total,
    limit: payload.limit,
    offset: payload.offset,
    hasMore: payload.has_more,
  }
}

function mapSourceCollectionRun(payload: BackendSourceCollectionRun): SourceCollectionRun {
  return {
    id: payload.id,
    sourceCollectionId: payload.source_collection_id,
    sourceCollectionNameAtStart: payload.source_collection_name_at_start,
    sourceCount: payload.source_count,
    processedCount: payload.processed_count,
    successCount: payload.success_count,
    failureCount: payload.failure_count,
    startedAt: payload.started_at,
    completedAt: payload.completed_at,
    status: payload.status,
    trigger: payload.trigger,
    mode: payload.mode ?? "once",
    continuousSubscriptionId: payload.continuous_subscription_id ?? null,
    continuousCycleNumber: payload.continuous_cycle_number ?? null,
    error: payload.error,
    sources: payload.sources.map((source) => ({
      id: source.id,
      sourceId: source.source_id,
      position: source.position,
      sourceName: source.source_name,
      platform: source.platform,
      status: source.status,
      startedAt: source.started_at,
      completedAt: source.completed_at,
      error: source.error,
    })),
  }
}

function mapSourceCollection(row: BackendSourceCollection): SourceCollectionSummary {
  return {
    id: row.id,
    name: row.name,
    description: row.description,
    sourceCount: row.source_count,
    maximumSources: row.maximum_sources,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    activeIngestRunId: row.active_ingest_run_id,
    activeIngestStatus: row.active_ingest_status,
    activeIngestSourceCount: row.active_ingest_source_count,
    activeIngestProcessedCount: row.active_ingest_processed_count,
    activeIngestSuccessCount: row.active_ingest_success_count,
    activeIngestFailureCount: row.active_ingest_failure_count,
    continuousSubscriptionId: row.continuous_subscription_id ?? null,
    continuousMode: row.continuous_mode ?? null,
    continuousStatus: row.continuous_status ?? null,
    continuousIntervalMinutes: row.continuous_interval_minutes ?? null,
    continuousStartedAt: row.continuous_started_at ?? null,
    continuousStoppedAt: row.continuous_stopped_at ?? null,
    continuousLastCycleAt: row.continuous_last_cycle_at ?? null,
    continuousNextCycleAt: row.continuous_next_cycle_at ?? null,
    continuousLastSuccessAt: row.continuous_last_success_at ?? null,
    continuousCycleCount: row.continuous_cycle_count ?? null,
    continuousLastCycleStatus: row.continuous_last_cycle_status ?? null,
    continuousLastError: row.continuous_last_error ?? null,
    continuousCurrentCycleJobId: row.continuous_current_cycle_job_id ?? null,
    continuousCurrentCycleRunId: row.continuous_current_cycle_run_id ?? null,
  }
}

function mapSourceCollectionSubscription(
  row: BackendSourceCollectionSubscription,
): SourceCollectionSubscription {
  return {
    id: row.id,
    sourceCollectionId: row.source_collection_id,
    sourceCollectionName: row.source_collection_name,
    mode: row.mode,
    status: row.status,
    createdAt: row.created_at,
    startedAt: row.started_at,
    stoppedAt: row.stopped_at,
    lastCycleAt: row.last_cycle_at,
    nextCycleAt: row.next_cycle_at,
    lastSuccessAt: row.last_success_at,
    cycleCount: row.cycle_count,
    intervalMinutes: row.interval_minutes,
    createdBy: row.created_by,
    lastCycleStatus: row.last_cycle_status,
    lastError: row.last_error,
    currentCycleJobId: row.current_cycle_job_id,
    currentCycleRunId: row.current_cycle_run_id,
  }
}

function mapMembershipChange(row: BackendSourceCollectionMembershipChange): SourceCollectionMembershipChange {
  return {
    collectionId: row.collection_id,
    addedSourceIds: row.added_source_ids,
    removedSourceIds: row.removed_source_ids,
    alreadyMemberSourceIds: row.already_member_source_ids,
    missingSourceIds: row.missing_source_ids,
    sourceCount: row.source_count,
    maximumSources: row.maximum_sources,
  }
}

function buildSourceQuery(filters: SourcePageFilters): string {
  const params = new URLSearchParams()
  if (filters.search?.trim()) params.set("search", filters.search.trim())
  if (filters.platform) params.set("platform", filters.platform)
  if (filters.sourceGroup) params.set("source_group", filters.sourceGroup)
  if (filters.collectionId) params.set("collection_id", filters.collectionId)
  if (filters.unassigned) params.set("unassigned", "true")
  if (filters.excludeCollectionId) params.set("exclude_collection_id", filters.excludeCollectionId)
  params.set("limit", String(filters.limit ?? 50))
  params.set("offset", String(filters.offset ?? 0))
  const query = params.toString()
  return query ? `?${query}` : ""
}

function jsonRequest(method: "DELETE" | "PATCH" | "POST", body: unknown): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }
}

function isAbortSignal(value: SourcePageFilters | AbortSignal): value is AbortSignal {
  return typeof AbortSignal !== "undefined" && value instanceof AbortSignal
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
    iconUrl: row.icon_url ?? null,
    iconSource: row.icon_source ?? null,
    iconUpdatedAt: row.icon_updated_at ?? null,
    iconStatus: row.icon_status ?? "pending",
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
