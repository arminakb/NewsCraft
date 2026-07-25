import type {
  ArticleCollection,
  ArticleImage,
  ArticleFacets,
  ArticleFilters,
  ArticlePage,
  ArticleSort,
  ArticleStorySummary,
  ArticleSummary,
} from "./types"

import { apiRequest, apiRequestVoid } from "@/lib/http"

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const AWARE_INSTANT_PATTERN = /(?:Z|[+-]\d{2}:\d{2})$/

export async function getArticles(input: {
  sort: ArticleSort
  query?: string
  filters?: ArticleFilters
  collectionId?: string | null
  cursor?: string | null
  limit?: number
}): Promise<ArticlePage> {
  const params = new URLSearchParams({
    sort: input.sort,
    limit: String(input.limit ?? 50),
  })
  if (input.query) params.set("q", input.query)
  if (input.collectionId) params.set("collection_id", input.collectionId)
  if (input.cursor) params.set("cursor", input.cursor)
  appendFilters(params, input.filters)
  return decodeArticlePage(await apiRequest<unknown>(`/articles?${params.toString()}`))
}

export async function getArticleCollections(): Promise<ArticleCollection[]> {
  return decodeArticleCollections(await apiRequest<unknown>("/article-collections"))
}

export async function createArticleCollection(name: string): Promise<ArticleCollection> {
  return decodeArticleCollection(await apiRequest<unknown>("/article-collections", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  }), "Invalid Article collection response")
}

export async function renameArticleCollection(collectionId: string, name: string): Promise<ArticleCollection> {
  return decodeArticleCollection(await apiRequest<unknown>(`/article-collections/${collectionId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  }), "Invalid Article collection response")
}

export async function deleteArticleCollection(collectionId: string): Promise<void> {
  await apiRequestVoid(`/article-collections/${collectionId}`, { method: "DELETE" })
}

export async function saveArticleToCollection(collectionId: string, articleId: string): Promise<void> {
  await apiRequestVoid(`/article-collections/${collectionId}/articles/${articleId}`, { method: "PUT" })
}

export async function removeArticleFromCollection(collectionId: string, articleId: string): Promise<void> {
  await apiRequestVoid(`/article-collections/${collectionId}/articles/${articleId}`, { method: "DELETE" })
}

export function decodeArticleCollections(value: unknown): ArticleCollection[] {
  const message = "Invalid Article collections response"
  if (!Array.isArray(value)) throw new Error(message)
  return value.map((item) => decodeArticleCollection(item, message))
}

function decodeArticleCollection(value: unknown, message: string): ArticleCollection {
  const row = exactObject(value, ["id", "name", "article_count", "created_at", "updated_at"], message)
  const name = string(row.name, message)
  if (name !== name.trim() || name.length > 60) throw new Error(message)
  return {
    id: uuid(row.id, message),
    name,
    articleCount: integer(row.article_count, message, 0),
    createdAt: timestamp(row.created_at, message),
    updatedAt: timestamp(row.updated_at, message),
  }
}

export async function getArticleFacets(): Promise<ArticleFacets> {
  return decodeArticleFacets(await apiRequest<unknown>("/articles/facets"))
}

export function decodeArticleFacets(value: unknown): ArticleFacets {
  const message = "Invalid Article facets response"
  const facets = exactObject(value, ["languages", "topics", "content_types", "sources", "coverage"], message)
  if (!Array.isArray(facets.languages) || !Array.isArray(facets.topics)
    || !Array.isArray(facets.content_types) || !Array.isArray(facets.sources)
    || !Array.isArray(facets.coverage)) throw new Error(message)
  return {
    languages: facets.languages.map((item) => decodeFacetValue(item, message)),
    topics: facets.topics.map((item) => decodeFacetValue(item, message)),
    contentTypes: facets.content_types.map((item) => decodeFacetValue(item, message)),
    sources: facets.sources.map((item) => {
      const source = exactObject(item, ["id", "name", "platform", "count"], message)
      return {
        id: uuid(source.id, message),
        name: string(source.name, message),
        platform: string(source.platform, message),
        count: integer(source.count, message, 1),
      }
    }),
    coverage: facets.coverage.map((item) => {
      const facet = exactObject(item, ["value", "count"], message)
      return {
        value: oneOf(facet.value, ["ungrouped", "incomplete", "complete"] as const, message),
        count: integer(facet.count, message, 1),
      }
    }),
  }
}

function decodeFacetValue(value: unknown, message: string) {
  const facet = exactObject(value, ["value", "count"], message)
  return { value: string(facet.value, message), count: integer(facet.count, message, 1) }
}

function appendFilters(params: URLSearchParams, filters?: ArticleFilters) {
  if (!filters) return
  for (const value of filters.languages) params.append("language", value)
  for (const value of filters.topics) params.append("topic", value)
  for (const value of filters.contentTypes) params.append("content_type", value)
  for (const value of filters.sourceIds) params.append("source_id", value)
  for (const value of filters.coverage) params.append("coverage", value)
  if (filters.hasImage !== null) params.set("has_image", String(filters.hasImage))
  if (filters.scoreMin !== null) params.set("score_min", String(filters.scoreMin))
  if (filters.scoreMax !== null) params.set("score_max", String(filters.scoreMax))
  if (filters.dateFrom) params.set("date_from", `${filters.dateFrom}T00:00:00Z`)
  if (filters.dateTo) params.set("date_to", `${nextUtcDate(filters.dateTo)}T00:00:00Z`)
}

function nextUtcDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

export function decodeArticlePage(value: unknown): ArticlePage {
  const message = "Invalid Articles response"
  const page = exactObject(value, ["items", "next_cursor", "result_count"], message)
  if (!Array.isArray(page.items)) throw new Error(message)
  return {
    items: page.items.map((item) => decodeArticle(item, message)),
    nextCursor: nullableString(page.next_cursor, message),
    resultCount: integer(page.result_count, message, 0),
  }
}

function decodeArticle(value: unknown, message: string): ArticleSummary {
  const row = exactObject(value, [
    "id",
    "title",
    "summary",
    "excerpt",
    "source",
    "canonical_url",
    "published_at",
    "sort_at",
    "display_at",
    "date_basis",
    "score",
    "content_type",
    "topic",
    "domain",
    "language",
    "direction",
    "coverage",
    "image",
    "has_image",
    "marked",
    "marked_at",
    "saved",
    "saved_collection_ids",
    "article_readiness",
  ], message)
  const source = exactObject(row.source, ["id", "name", "platform", "homepage_url"], message)
  const coverage = exactObject(row.coverage, ["state", "stories"], message)
  const readiness = exactObject(row.article_readiness, ["ready"], message)
  if (!Array.isArray(coverage.stories)) throw new Error(message)

  const direction = nullableString(row.direction, message)
  if (direction !== null && direction !== "ltr" && direction !== "rtl") throw new Error(message)
  const dateBasis = oneOf(row.date_basis, ["published", "collected"] as const, message)
  const coverageState = oneOf(coverage.state, ["ungrouped", "incomplete", "complete"] as const, message)
  const marked = boolean(row.marked, message)
  if (marked || row.marked_at !== null) throw new Error(message)
  const saved = boolean(row.saved, message)
  if (!Array.isArray(row.saved_collection_ids)) throw new Error(message)
  const savedCollectionIds = row.saved_collection_ids.map((value) => uuid(value, message))
  if (saved !== (savedCollectionIds.length > 0)) throw new Error(message)
  const image = row.image === null ? null : decodeImage(row.image, message)
  const hasImage = boolean(row.has_image, message)
  if (hasImage !== (image !== null)) throw new Error(message)

  return {
    id: uuid(row.id, message),
    title: nullableString(row.title, message, true),
    summary: nullableString(row.summary, message, true),
    excerpt: boundedExcerpt(row.excerpt, message),
    source: {
      id: nullableUuid(source.id, message),
      name: nullableString(source.name, message),
      platform: nullableString(source.platform, message),
      homepageUrl: nullableHttpUrl(source.homepage_url, message),
    },
    canonicalUrl: nullableHttpUrl(row.canonical_url, message),
    publishedAt: nullableTimestamp(row.published_at, message),
    sortAt: timestamp(row.sort_at, message),
    displayAt: timestamp(row.display_at, message),
    dateBasis,
    score: integer(row.score, message),
    contentType: string(row.content_type, message),
    topic: nullableString(row.topic, message),
    domain: nullableString(row.domain, message),
    language: nullableString(row.language, message),
    direction,
    coverage: {
      state: coverageState,
      stories: coverage.stories.map((story) => decodeStory(story, message)),
    },
    articleReadiness: { ready: boolean(readiness.ready, message) },
    image,
    hasImage,
    marked: false,
    markedAt: null,
    saved,
    savedCollectionIds,
  }
}

function decodeStory(value: unknown, message: string): ArticleStorySummary {
  const row = exactObject(value, ["id", "title", "editorial_state", "complete", "score"], message)
  return {
    id: uuid(row.id, message),
    title: string(row.title, message),
    editorialState: string(row.editorial_state, message),
    complete: boolean(row.complete, message),
    score: integer(row.score, message, 0, 100),
  }
}

function decodeImage(value: unknown, message: string): ArticleImage {
  const row = exactObject(value, [
    "id", "url", "kind", "width", "height", "alt_text", "fetch_status",
  ], message)
  if (row.kind !== "image") throw new Error(message)
  return {
    id: uuid(row.id, message),
    url: httpUrl(row.url, message),
    kind: "image",
    width: nullableInteger(row.width, message, 1),
    height: nullableInteger(row.height, message, 1),
    altText: nullableString(row.alt_text, message, true),
    fetchStatus: string(row.fetch_status, message),
  }
}

function exactObject(value: unknown, keys: readonly string[], message: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(message)
  const row = value as Record<string, unknown>
  const actual = Object.keys(row).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error(message)
  }
  return row
}

function string(value: unknown, message: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && !value.trim())) throw new Error(message)
  return value
}

function nullableString(value: unknown, message: string, allowEmpty = false): string | null {
  return value === null ? null : string(value, message, allowEmpty)
}

function uuid(value: unknown, message: string): string {
  const candidate = string(value, message)
  if (!UUID_PATTERN.test(candidate)) throw new Error(message)
  return candidate
}

function nullableUuid(value: unknown, message: string): string | null {
  return value === null ? null : uuid(value, message)
}

function timestamp(value: unknown, message: string): string {
  const candidate = string(value, message)
  if (!AWARE_INSTANT_PATTERN.test(candidate) || Number.isNaN(Date.parse(candidate))) throw new Error(message)
  return candidate
}

function nullableTimestamp(value: unknown, message: string): string | null {
  return value === null ? null : timestamp(value, message)
}

function httpUrl(value: unknown, message: string): string {
  const candidate = string(value, message)
  try {
    const parsed = new URL(candidate)
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error(message)
  } catch {
    throw new Error(message)
  }
  return candidate
}

function nullableHttpUrl(value: unknown, message: string): string | null {
  return value === null ? null : httpUrl(value, message)
}

function integer(value: unknown, message: string, minimum?: number, maximum?: number): number {
  if (!Number.isInteger(value)) throw new Error(message)
  const candidate = value as number
  if ((minimum !== undefined && candidate < minimum) || (maximum !== undefined && candidate > maximum)) {
    throw new Error(message)
  }
  return candidate
}

function nullableInteger(value: unknown, message: string, minimum?: number): number | null {
  return value === null ? null : integer(value, message, minimum)
}

function boolean(value: unknown, message: string): boolean {
  if (typeof value !== "boolean") throw new Error(message)
  return value
}

function oneOf<const T extends readonly string[]>(value: unknown, values: T, message: string): T[number] {
  if (typeof value !== "string" || !values.includes(value)) throw new Error(message)
  return value as T[number]
}

function boundedExcerpt(value: unknown, message: string): string | null {
  const excerpt = nullableString(value, message, true)
  if (excerpt !== null && excerpt.length > 500) throw new Error(message)
  return excerpt
}
