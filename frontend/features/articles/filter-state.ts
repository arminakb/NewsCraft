import type { ArticleFilters, ArticleSort } from "./types"

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const COVERAGE = new Set(["ungrouped", "incomplete", "complete"])

export const EMPTY_ARTICLE_FILTERS: ArticleFilters = {
  languages: [], topics: [], contentTypes: [], sourceIds: [], coverage: [],
  hasImage: null, scoreMin: null, scoreMax: null, dateFrom: null, dateTo: null,
}

export function readArticleState(params: URLSearchParams | Readonly<URLSearchParams>) {
  const scoreMin = integerParam(params.get("score_min"))
  const scoreMax = integerParam(params.get("score_max"))
  const dateFrom = dateParam(params.get("date_from"))
  const dateTo = dateParam(params.get("date_to"))
  const validScoreRange = scoreMin === null || scoreMax === null || scoreMin <= scoreMax
  const validDateRange = dateFrom === null || dateTo === null || dateFrom <= dateTo
  return {
    sort: params.get("sort") === "score" ? "score" as ArticleSort : "newest" as ArticleSort,
    query: normalizeArticleSearch(params.get("q") ?? ""),
    filters: {
      languages: textParams(params.getAll("language")),
      topics: textParams(params.getAll("topic")),
      contentTypes: textParams(params.getAll("content_type")),
      sourceIds: unique(params.getAll("source_id").filter((value) => UUID_PATTERN.test(value))),
      coverage: unique(params.getAll("coverage").filter((value) => COVERAGE.has(value))) as ArticleFilters["coverage"],
      hasImage: params.get("has_image") === "true" ? true : params.get("has_image") === "false" ? false : null,
      scoreMin: validScoreRange ? scoreMin : null,
      scoreMax: validScoreRange ? scoreMax : null,
      dateFrom: validDateRange ? dateFrom : null,
      dateTo: validDateRange ? dateTo : null,
    },
  }
}

export function readArticlePage(params: URLSearchParams | Readonly<URLSearchParams>) {
  const raw = params.get("page")
  if (raw === null || !/^\d+$/.test(raw)) return 1
  const page = Number(raw)
  return Number.isSafeInteger(page) && page >= 1 && page <= 1_000_000 ? page : 1
}

export function readArticleCursor(params: URLSearchParams | Readonly<URLSearchParams>) {
  const cursor = params.get("cursor")?.trim()
  return cursor || null
}

export function normalizeArticleSearch(value: string) {
  return value.trim()
}

export function writeArticleSearch(current: URLSearchParams, query: string) {
  const params = new URLSearchParams(current)
  params.delete("page")
  params.delete("cursor")
  const normalized = normalizeArticleSearch(query)
  if (normalized) params.set("q", normalized)
  else params.delete("q")
  return params
}

export function writeArticleState(current: URLSearchParams, sort: ArticleSort, filters: ArticleFilters) {
  const params = new URLSearchParams(current)
  for (const key of ["sort", "language", "topic", "content_type", "source_id", "coverage", "has_image", "score_min", "score_max", "date_from", "date_to", "page", "cursor"]) {
    params.delete(key)
  }
  if (sort !== "newest") params.set("sort", sort)
  for (const value of filters.languages) params.append("language", value)
  for (const value of filters.topics) params.append("topic", value)
  for (const value of filters.contentTypes) params.append("content_type", value)
  for (const value of filters.sourceIds) params.append("source_id", value)
  for (const value of filters.coverage) params.append("coverage", value)
  if (filters.hasImage !== null) params.set("has_image", String(filters.hasImage))
  if (filters.scoreMin !== null) params.set("score_min", String(filters.scoreMin))
  if (filters.scoreMax !== null) params.set("score_max", String(filters.scoreMax))
  if (filters.dateFrom) params.set("date_from", filters.dateFrom)
  if (filters.dateTo) params.set("date_to", filters.dateTo)
  return params
}

export function activeFilterCount(filters: ArticleFilters) {
  return filters.languages.length + filters.topics.length + filters.contentTypes.length
    + filters.sourceIds.length + filters.coverage.length
    + Number(filters.hasImage !== null) + Number(filters.scoreMin !== null)
    + Number(filters.scoreMax !== null) + Number(filters.dateFrom !== null) + Number(filters.dateTo !== null)
}

export function filtersEqual(left: ArticleFilters, right: ArticleFilters) {
  return JSON.stringify(left) === JSON.stringify(right)
}

function textParams(values: string[]) {
  return unique(values.map((value) => value.trim()).filter((value) => value.length > 0 && value.length <= 200)).slice(0, 50)
}

function unique<T>(values: T[]) {
  return [...new Set(values)]
}

function integerParam(value: string | null) {
  if (value === null || !/^-?\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

function dateParam(value: string | null) {
  if (value === null || !DATE_PATTERN.test(value)) return null
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value ? value : null
}
