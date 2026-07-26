import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { apiRequest, apiRequestVoid } from "@/lib/http"

import type {
  ArticleCollection,
  ArticleFacets,
  ArticleFilters,
  ArticlePage,
  ArticleSort,
} from "./types"

type Schemas = components["schemas"]

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
  return camelize(await apiRequest<Schemas["ArticleListOut"]>(`/articles?${params.toString()}`))
}

export async function getArticleCollections(): Promise<ArticleCollection[]> {
  return camelize(await apiRequest<Schemas["ArticleCollectionOut"][]>("/article-collections"))
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
