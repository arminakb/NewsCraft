import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { DEFAULT_TIME_ZONE } from "@/lib/date-time"
import { apiRequest, apiRequestVoid } from "@/lib/http"

import { appendArticleFilterParams } from "./filter-params"
import type {
  ArticleCollection,
  ArticleFacets,
  ArticleFilters,
  ArticleDetail,
  ArticlePage,
  ArticleSort,
  FeedClearResult,
  FeedSummary,
} from "./types"

type Schemas = components["schemas"]

export async function getArticles(input: {
  sort: ArticleSort
  query?: string
  filters?: ArticleFilters
  collectionId?: string | null
  cursor?: string | null
  limit?: number
  timezone?: string
}, signal?: AbortSignal): Promise<ArticlePage> {
  const params = new URLSearchParams({
    sort: input.sort,
    limit: String(input.limit ?? 50),
  })
  if (input.query) params.set("q", input.query)
  if (input.collectionId) params.set("collection_id", input.collectionId)
  if (input.cursor) params.set("cursor", input.cursor)
  appendArticleFilterParams(params, input.filters, {
    mode: "request",
    timezone: input.timezone ?? DEFAULT_TIME_ZONE,
  })
  const requestInit = signal ? { signal } : undefined
  return camelize(await apiRequest<Schemas["ArticleListOut"]>(`/articles?${params.toString()}`, requestInit))
}

export async function getArticle(articleId: string): Promise<ArticleDetail> {
  return camelize(await apiRequest<Schemas["ArticleDetailOut"]>(`/articles/${articleId}`))
}

export async function getArticleCollections(signal?: AbortSignal): Promise<ArticleCollection[]> {
  return camelize(await apiRequest<Schemas["ArticleCollectionOut"][]>("/article-collections", signal ? { signal } : undefined))
}

export async function createArticleCollection(name: string): Promise<ArticleCollection> {
  return camelize(await apiRequest<Schemas["ArticleCollectionOut"]>("/article-collections", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name } satisfies Schemas["ArticleCollectionNameIn"]),
  }))
}

export async function renameArticleCollection(collectionId: string, name: string): Promise<ArticleCollection> {
  return camelize(await apiRequest<Schemas["ArticleCollectionOut"]>(`/article-collections/${collectionId}`, {
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
  return camelize(await apiRequest<Schemas["ArticleFacetsOut"]>("/articles/facets"))
}

export async function getFeedSummary(signal?: AbortSignal): Promise<FeedSummary> {
  return camelize(await apiRequest<Schemas["FeedSummaryOut"]>("/feed/summary", signal ? { signal } : undefined))
}

export async function clearFeed(): Promise<FeedClearResult> {
  return camelize(await apiRequest<Schemas["FeedClearOut"]>("/feed/clear", { method: "POST" }))
}

