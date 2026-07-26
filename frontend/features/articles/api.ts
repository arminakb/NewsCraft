import type { components } from "@/lib/api/generated"
import { apiRequest, apiRequestVoid } from "@/lib/http"

import type {
  ArticleCollection,
  ArticleFacets,
  ArticleFilters,
  ArticlePage,
  ArticleSort,
  ArticleSummary,
} from "./types"

type Schemas = components["schemas"]
type ArticleCollectionWire = Schemas["ArticleCollectionOut"]
type ArticleFacetsWire = Schemas["ArticleFacetsOut"]
type ArticlePageWire = Schemas["ArticleListOut"]
type ArticleSummaryWire = Schemas["ArticleSummaryOut"]

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
  return mapArticlePage(await apiRequest<ArticlePageWire>(`/articles?${params.toString()}`))
}

export async function getArticleCollections(): Promise<ArticleCollection[]> {
  return mapArticleCollections(await apiRequest<ArticleCollectionWire[]>("/article-collections"))
}

export async function createArticleCollection(name: string): Promise<ArticleCollection> {
  return mapArticleCollection(await apiRequest<ArticleCollectionWire>("/article-collections", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name } satisfies Schemas["ArticleCollectionNameIn"]),
  }))
}

export async function renameArticleCollection(collectionId: string, name: string): Promise<ArticleCollection> {
  return mapArticleCollection(await apiRequest<ArticleCollectionWire>(`/article-collections/${collectionId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name } satisfies Schemas["ArticleCollectionNameIn"]),
  }))
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

export async function getArticleFacets(): Promise<ArticleFacets> {
  return mapArticleFacets(await apiRequest<ArticleFacetsWire>("/articles/facets"))
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

function mapArticleCollections(rows: ArticleCollectionWire[]): ArticleCollection[] {
  return rows.map(mapArticleCollection)
}

function mapArticleCollection(row: ArticleCollectionWire): ArticleCollection {
  return {
    id: row.id,
    name: row.name,
    articleCount: row.article_count,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

function mapArticleFacets(row: ArticleFacetsWire): ArticleFacets {
  return {
    languages: row.languages,
    topics: row.topics,
    contentTypes: row.content_types,
    sources: row.sources,
    coverage: row.coverage,
  }
}

function mapArticlePage(row: ArticlePageWire): ArticlePage {
  return {
    items: row.items.map(mapArticle),
    nextCursor: row.next_cursor,
    resultCount: row.result_count,
  }
}

function mapArticle(row: ArticleSummaryWire): ArticleSummary {
  return {
    id: row.id,
    title: row.title,
    summary: row.summary,
    excerpt: row.excerpt,
    source: {
      id: row.source.id,
      name: row.source.name,
      platform: row.source.platform,
      homepageUrl: row.source.homepage_url,
    },
    canonicalUrl: row.canonical_url,
    publishedAt: row.published_at,
    sortAt: row.sort_at,
    displayAt: row.display_at,
    dateBasis: row.date_basis,
    score: row.score,
    contentType: row.content_type,
    topic: row.topic,
    domain: row.domain,
    language: row.language,
    direction: row.direction,
    coverage: {
      state: row.coverage.state,
      stories: row.coverage.stories.map((story) => ({
        id: story.id,
        title: story.title,
        editorialState: story.editorial_state,
        complete: story.complete,
        score: story.score,
      })),
    },
    articleReadiness: { ready: row.article_readiness.ready },
    image: row.image === null ? null : {
      id: row.image.id,
      url: row.image.url,
      kind: "image",
      width: row.image.width,
      height: row.image.height,
      altText: row.image.alt_text,
      fetchStatus: row.image.fetch_status,
    },
    hasImage: row.has_image,
    marked: false,
    markedAt: null,
    saved: row.saved,
    savedCollectionIds: row.saved_collection_ids,
  }
}
