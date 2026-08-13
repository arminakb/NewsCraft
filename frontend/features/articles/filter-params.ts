import { zonedLocalDateTimeToUtc } from "@/lib/date-time"

import type { ArticleFilters } from "./types"

/**
 * Single writer for the article filter query string. The browser URL keeps the
 * bare calendar dates the operator picked; the backend request converts those
 * dates into instants at the boundaries of the configured display timezone.
 */
export const ARTICLE_FILTER_PARAM_KEYS = [
  "language",
  "topic",
  "content_type",
  "source_id",
  "coverage",
  "has_image",
  "score_min",
  "score_max",
  "date_from",
  "date_to",
] as const

export type ArticleFilterParamTarget =
  | { mode: "url" }
  | { mode: "request"; timezone: string }

export function appendArticleFilterParams(
  params: URLSearchParams,
  filters: ArticleFilters | undefined,
  target: ArticleFilterParamTarget,
) {
  if (!filters) return
  for (const value of filters.languages) params.append("language", value)
  for (const value of filters.topics) params.append("topic", value)
  for (const value of filters.contentTypes) params.append("content_type", value)
  for (const value of filters.sourceIds) params.append("source_id", value)
  for (const value of filters.coverage) params.append("coverage", value)
  if (filters.hasImage !== null) params.set("has_image", String(filters.hasImage))
  if (filters.scoreMin !== null) params.set("score_min", String(filters.scoreMin))
  if (filters.scoreMax !== null) params.set("score_max", String(filters.scoreMax))
  if (filters.dateFrom) params.set("date_from", dateBound(filters.dateFrom, target, false))
  if (filters.dateTo) params.set("date_to", dateBound(filters.dateTo, target, true))
}

function dateBound(value: string, target: ArticleFilterParamTarget, exclusiveEnd: boolean) {
  if (target.mode === "url") return value
  const date = exclusiveEnd ? nextCalendarDate(value) : value
  return dayStartInstant(date, target.timezone)
}

/**
 * Calendar dates come from the filter UI and are read by the operator in the
 * configured display timezone, so their day boundaries must be resolved in
 * that zone rather than in UTC. The UTC boundary is only a fallback for the
 * rare local midnight that a DST jump skips.
 */
function dayStartInstant(date: string, timezone: string) {
  return zonedLocalDateTimeToUtc(`${date}T00:00`, timezone) ?? `${date}T00:00:00Z`
}

function nextCalendarDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}
