import { decodeContentPackage } from "@/features/packages/api"
import type { Platform } from "@/features/packages/types"
import { apiRequest } from "@/lib/http"

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const AWARE_INSTANT_PATTERN = /(?:Z|[+-]\d{2}:\d{2})$/
const PLATFORMS = ["telegram", "instagram", "x", "blog"] as const

export type CursorPage<T> = {
  items: T[]
  nextCursor: string | null
}

export type LibraryOriginal = {
  id: string
  title: string | null
  status: string
  sourceId: string | null
  sourceName: string | null
  sourceUrl: string | null
  publishedAt: string | null
  sortAt: string
}

export type LibraryStory = {
  id: string
  title: string
  status: string
  evidenceCount: number
  updatedAt: string
}

export type LibraryEvidence = {
  id: string
  storyId: string
  contentItemId: string | null
  evidenceKey: string
  title: string | null
  sourceUrl: string | null
  authors: string[]
  publishedAt: string | null
  capturedAt: string
  contentSha256: string
  excerpt: string
}

export type LibraryResearchRun = {
  id: string
  storyId: string
  requestedMode: "manual" | "auto_if_incomplete"
  backend: string | null
  status: string
  budget: { maxQueries: number; maxPages: number; maxElapsedSeconds: number }
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  attemptCount: number
  sourceCount: number
  resultRevisionId: string | null
  errorSummary: string | null
}

export type LibraryDraft = {
  packId: string
  storyId: string
  platform: Platform
  revisionId: string
  revisionNumber: number
  approvalState: string
  updatedAt: string
}

export type LibraryExport = {
  id: string
  status: string
  finishedAt: string | null
  contentPackId: string | null
  downloads: string[]
  errorSummary: string | null
}

export type LibraryPublication = {
  id: string
  kind: "telegram_publication" | "manual_publication"
  platform: Platform
  revisionId: string
  occurredAt: string
  status: string
  externalUrl: string | null
  actionUrl: string
}

export async function getLibraryOriginals(
  cursor?: string | null,
): Promise<CursorPage<LibraryOriginal>> {
  return decodeLibraryOriginalPage(
    await apiRequest<unknown>(`/library/originals?${cursorQuery(cursor)}`),
  )
}

export async function getLibraryStories(cursor?: string | null): Promise<CursorPage<LibraryStory>> {
  return decodeLibraryStoryPage(
    await apiRequest<unknown>(`/stories?${cursorQuery(cursor)}`),
  )
}

export async function getLibraryEvidence(cursor?: string | null): Promise<CursorPage<LibraryEvidence>> {
  return decodeLibraryEvidencePage(
    await apiRequest<unknown>(`/library/evidence?${cursorQuery(cursor)}`),
  )
}

export async function getLibraryResearchRuns(
  cursor?: string | null,
): Promise<CursorPage<LibraryResearchRun>> {
  return decodeLibraryResearchPage(
    await apiRequest<unknown>(`/library/research-runs?${cursorQuery(cursor)}`),
  )
}

export async function getLibraryResearchRun(runId: string): Promise<LibraryResearchRun> {
  const expectedId = uuid(runId, "Invalid Library research run ID")
  const run = decodeLibraryResearchRun(
    await apiRequest<unknown>(`/library/research-runs/${encodeURIComponent(expectedId)}`),
  )
  if (run.id !== expectedId) throw new Error("Library research run identity mismatch")
  return run
}

export async function getLibraryDrafts(): Promise<LibraryDraft[]> {
  const value = await apiRequest<unknown>("/content-packs")
  const packages = array(value, "Invalid Library content-pack list").map(decodeContentPackage)
  return packages.flatMap((pack) =>
    pack.variants.flatMap((variant) => {
      const revision = variant.currentRevision
      return revision
        ? [{
            packId: pack.id,
            storyId: pack.storyId,
            platform: variant.platform,
            revisionId: revision.id,
            revisionNumber: revision.revisionNumber,
            approvalState: revision.approvalState,
            updatedAt: pack.updatedAt,
          }]
        : []
    }),
  )
}

export async function getLibraryExports(cursor?: string | null): Promise<CursorPage<LibraryExport>> {
  return decodeLibraryExportPage(
    await apiRequest<unknown>(`/exports?${cursorQuery(cursor)}`),
  )
}

export async function getLibraryPublications(
  cursor?: string | null,
): Promise<CursorPage<LibraryPublication>> {
  return decodeLibraryPublicationPage(
    await apiRequest<unknown>(`/publications?${cursorQuery(cursor)}`),
  )
}

export function decodeLibraryOriginalPage(value: unknown): CursorPage<LibraryOriginal> {
  return decodePage(value, decodeLibraryOriginal, "Invalid Library originals response")
}

export function decodeLibraryStoryPage(value: unknown): CursorPage<LibraryStory> {
  return decodePage(value, decodeLibraryStory, "Invalid Library stories response")
}

export function decodeLibraryEvidencePage(value: unknown): CursorPage<LibraryEvidence> {
  return decodePage(value, decodeLibraryEvidence, "Invalid Library evidence response")
}

export function decodeLibraryResearchPage(value: unknown): CursorPage<LibraryResearchRun> {
  return decodePage(value, decodeLibraryResearchRun, "Invalid Library research response")
}

export function decodeLibraryExportPage(value: unknown): CursorPage<LibraryExport> {
  return decodePage(value, decodeLibraryExport, "Invalid Library exports response")
}

export function decodeLibraryPublicationPage(value: unknown): CursorPage<LibraryPublication> {
  return decodePage(value, decodeLibraryPublication, "Invalid Library publications response")
}

function decodeLibraryOriginal(value: unknown): LibraryOriginal {
  const message = "Invalid Library original"
  const row = exactObject(value, [
    "id", "title", "status", "source_id", "source_name", "source_url",
    "published_at", "sort_at",
  ], message)
  return {
    id: uuid(row.id, message),
    title: nullableString(row.title, message, true),
    status: string(row.status, message),
    sourceId: nullableUuid(row.source_id, message),
    sourceName: nullableString(row.source_name, message),
    sourceUrl: nullableHttpUrl(row.source_url, message),
    publishedAt: nullableTimestamp(row.published_at, message),
    sortAt: timestamp(row.sort_at, message),
  }
}

function decodeLibraryStory(value: unknown): LibraryStory {
  const message = "Invalid Library story"
  const row = exactObject(value, [
    "id", "title", "status", "primary_language", "superseded_by_id",
    "evidence_count", "latest_evidence_at", "completeness", "evidence_set_hash",
    "created_at", "updated_at",
  ], message)
  const completeness = exactObject(row.completeness, [
    "complete", "score", "reasons", "independent_source_count",
    "body_character_count", "has_primary_evidence",
  ], message)
  boolean(completeness.complete, message)
  boundedInteger(completeness.score, 0, 100, message)
  stringArray(completeness.reasons, message)
  nonNegativeInteger(completeness.independent_source_count, message)
  nonNegativeInteger(completeness.body_character_count, message)
  boolean(completeness.has_primary_evidence, message)
  string(row.primary_language, message)
  nullableUuid(row.superseded_by_id, message)
  nullableTimestamp(row.latest_evidence_at, message)
  sha256(row.evidence_set_hash, message)
  timestamp(row.created_at, message)
  return {
    id: uuid(row.id, message),
    title: string(row.title, message),
    status: string(row.status, message),
    evidenceCount: nonNegativeInteger(row.evidence_count, message),
    updatedAt: timestamp(row.updated_at, message),
  }
}

function decodeLibraryEvidence(value: unknown): LibraryEvidence {
  const message = "Invalid Library evidence snapshot"
  const row = exactObject(value, [
    "id", "story_id", "content_item_id", "evidence_key", "title", "source_url",
    "authors", "published_at", "captured_at", "content_sha256", "excerpt",
  ], message)
  const excerpt = string(row.excerpt, message, true)
  if (excerpt.length > 500 || excerpt !== excerpt.trim().replace(/\s+/g, " ")) {
    throw new Error(message)
  }
  return {
    id: uuid(row.id, message),
    storyId: uuid(row.story_id, message),
    contentItemId: nullableUuid(row.content_item_id, message),
    evidenceKey: string(row.evidence_key, message),
    title: nullableString(row.title, message, true),
    sourceUrl: nullableHttpUrl(row.source_url, message),
    authors: stringArray(row.authors, message, true),
    publishedAt: nullableTimestamp(row.published_at, message),
    capturedAt: timestamp(row.captured_at, message),
    contentSha256: sha256(row.content_sha256, message),
    excerpt,
  }
}

function decodeLibraryResearchRun(value: unknown): LibraryResearchRun {
  const message = "Invalid Library research run"
  const row = exactObject(value, [
    "id", "story_id", "requested_mode", "backend", "status", "budget", "created_at",
    "started_at", "finished_at", "attempt_count", "source_count",
    "result_story_revision_id", "error_summary",
  ], message)
  const budget = exactObject(
    row.budget,
    ["max_queries", "max_pages", "max_elapsed_seconds"],
    message,
  )
  const errorSummary = nullableString(row.error_summary, message, true)
  if (errorSummary !== null && errorSummary.length > 500) throw new Error(message)
  return {
    id: uuid(row.id, message),
    storyId: uuid(row.story_id, message),
    requestedMode: oneOf(row.requested_mode, ["manual", "auto_if_incomplete"] as const, message),
    backend: nullableString(row.backend, message),
    status: string(row.status, message),
    budget: {
      maxQueries: nonNegativeInteger(budget.max_queries, message),
      maxPages: nonNegativeInteger(budget.max_pages, message),
      maxElapsedSeconds: nonNegativeInteger(budget.max_elapsed_seconds, message),
    },
    createdAt: timestamp(row.created_at, message),
    startedAt: nullableTimestamp(row.started_at, message),
    finishedAt: nullableTimestamp(row.finished_at, message),
    attemptCount: nonNegativeInteger(row.attempt_count, message),
    sourceCount: nonNegativeInteger(row.source_count, message),
    resultRevisionId: nullableUuid(row.result_story_revision_id, message),
    errorSummary,
  }
}

function decodeLibraryExport(value: unknown): LibraryExport {
  const message = "Invalid Library export"
  const row = exactObject(value, [
    "export_id", "status", "finished_at", "artifact", "downloads", "error_code", "error_message",
  ], message)
  const exportId = uuid(row.export_id, message)
  const contentPackId = decodeExportArtifact(row.artifact, exportId)
  const downloads = stringArray(row.downloads, message).map((path) =>
    safeExportDownload(path, exportId)
  )
  if (downloads.length && contentPackId === null) throw new Error(message)
  nullableString(row.error_code, message)
  return {
    id: exportId,
    status: string(row.status, message),
    finishedAt: nullableTimestamp(row.finished_at, message),
    contentPackId,
    downloads,
    errorSummary: nullableString(row.error_message, message, true),
  }
}

function decodeExportArtifact(value: unknown, exportId: string): string | null {
  if (value === null) return null
  const message = "Invalid Library export artifact"
  const row = exactObject(value, [
    "export_id", "content_pack_id", "state", "manifest_file", "manifest_sha256",
    "archive_file", "archive_sha256", "manifest",
  ], message)
  if (uuid(row.export_id, message) !== exportId || row.state !== "complete" || row.manifest_file !== "manifest.json") {
    throw new Error(message)
  }
  sha256(row.manifest_sha256, message)
  const archiveFile = nullableString(row.archive_file, message)
  const archiveHash = row.archive_sha256 === null ? null : sha256(row.archive_sha256, message)
  if ((archiveFile === null) !== (archiveHash === null) || (archiveFile !== null && archiveFile !== "bundle.zip")) {
    throw new Error(message)
  }
  if (row.manifest === null || typeof row.manifest !== "object" || Array.isArray(row.manifest)) {
    throw new Error(message)
  }
  return uuid(row.content_pack_id, message)
}

function decodeLibraryPublication(value: unknown): LibraryPublication {
  const message = "Invalid Library publication"
  const row = exactObject(value, [
    "id", "kind", "platform", "revision_id", "occurred_at", "status", "external_url", "action_url",
  ], message)
  const id = uuid(row.id, message)
  const revisionId = uuid(row.revision_id, message)
  const kind = oneOf(
    row.kind,
    ["telegram_publication", "manual_publication"] as const,
    message,
  )
  const platform = oneOf(row.platform, PLATFORMS, message)
  if ((kind === "telegram_publication") !== (platform === "telegram")) throw new Error(message)
  const externalUrl = nullableHttpUrl(row.external_url, message)
  return {
    id,
    kind,
    platform,
    revisionId,
    occurredAt: timestamp(row.occurred_at, message),
    status: string(row.status, message),
    externalUrl,
    actionUrl: safeReviewAction(row.action_url, revisionId),
  }
}

function decodePage<T>(
  value: unknown,
  decodeItem: (item: unknown) => T,
  message: string,
): CursorPage<T> {
  const row = exactObject(value, ["items", "next_cursor"], message)
  return {
    items: array(row.items, message).map(decodeItem),
    nextCursor: nullableCursor(row.next_cursor, message),
  }
}

function cursorQuery(cursor?: string | null): string {
  const query = new URLSearchParams({ limit: "50" })
  if (cursor) query.set("cursor", cursor)
  return query.toString()
}

function exactObject<const K extends string>(
  value: unknown,
  keys: readonly K[],
  message: string,
): Record<K, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(message)
  const row = value as Record<string, unknown>
  const actual = Object.keys(row)
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key as K))) {
    throw new Error(message)
  }
  return row as Record<K, unknown>
}

function array(value: unknown, message: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(message)
  return value
}

function string(value: unknown, message: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && !value.trim())) throw new Error(message)
  return value
}

function nullableString(value: unknown, message: string, allowEmpty = false): string | null {
  return value === null ? null : string(value, message, allowEmpty)
}

function stringArray(value: unknown, message: string, allowEmpty = false): string[] {
  return array(value, message).map((item) => string(item, message, allowEmpty))
}

function boolean(value: unknown, message: string): boolean {
  if (typeof value !== "boolean") throw new Error(message)
  return value
}

function nonNegativeInteger(value: unknown, message: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) throw new Error(message)
  return value as number
}

function boundedInteger(value: unknown, minimum: number, maximum: number, message: string): number {
  const integer = nonNegativeInteger(value, message)
  if (integer < minimum || integer > maximum) throw new Error(message)
  return integer
}

function uuid(value: unknown, message: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) throw new Error(message)
  return value
}

function nullableUuid(value: unknown, message: string): string | null {
  return value === null ? null : uuid(value, message)
}

function sha256(value: unknown, message: string): string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) throw new Error(message)
  return value
}

function timestamp(value: unknown, message: string): string {
  const text = string(value, message)
  if (!AWARE_INSTANT_PATTERN.test(text) || Number.isNaN(Date.parse(text))) throw new Error(message)
  return text
}

function nullableTimestamp(value: unknown, message: string): string | null {
  return value === null ? null : timestamp(value, message)
}

function httpUrl(value: unknown, message: string): string {
  const text = string(value, message)
  try {
    const url = new URL(text)
    if (!(["http:", "https:"] as const).includes(url.protocol as "http:" | "https:") || url.username || url.password) {
      throw new Error(message)
    }
    return text
  } catch {
    throw new Error(message)
  }
}

function nullableHttpUrl(value: unknown, message: string): string | null {
  return value === null ? null : httpUrl(value, message)
}

function nullableCursor(value: unknown, message: string): string | null {
  if (value === null) return null
  const cursor = string(value, message)
  if (cursor.length > 1000 || !/^[A-Za-z0-9_-]+$/.test(cursor)) throw new Error(message)
  return cursor
}

function safeReviewAction(value: unknown, revisionId: string): string {
  const path = string(value, "Invalid Library publication action")
  if (path !== `/review/${revisionId}`) throw new Error("Invalid Library publication action")
  return path
}

function safeExportDownload(value: string, exportId: string): string {
  const message = "Invalid Library export download"
  const prefix = `/exports/${exportId}/download/`
  if (!value.startsWith(prefix) || value.includes("\\") || value.includes("?") || value.includes("#")) {
    throw new Error(message)
  }
  const encoded = value.slice(prefix.length)
  let decoded: string
  try {
    decoded = decodeURIComponent(encoded)
  } catch {
    throw new Error(message)
  }
  const parts = decoded.split("/")
  if (!decoded || parts.some((part) => !part || part === "." || part === ".." || !/^[A-Za-z0-9._-]+$/.test(part))) {
    throw new Error(message)
  }
  return value
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  choices: T,
  message: string,
): T[number] {
  if (typeof value !== "string" || !choices.includes(value)) throw new Error(message)
  return value as T[number]
}
