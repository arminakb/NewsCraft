import type { ArticleSummary } from "./types"

import { titleCase } from "@/lib/format"

type ClassificationKind = "content-type" | "topic" | "language"

export type ArticleCardClassification = {
  kind: ClassificationKind
  label: string
}

type ClassificationInput = Pick<ArticleSummary, "contentType" | "topic" | "language">

export function getArticleCardClassifications(article: ClassificationInput): ArticleCardClassification[] {
  const classifications: ArticleCardClassification[] = []
  const seen = new Set<string>()
  const contentType = article.contentType.trim()
  const topic = article.topic?.trim() || null
  const language = article.language?.trim() || null
  const genericArticle = normalize(contentType) === "article"

  const add = (kind: ClassificationKind, label: string) => {
    const key = normalize(label)
    if (!key || seen.has(key) || classifications.length === 3) return
    seen.add(key)
    classifications.push({ kind, label })
  }

  if (!genericArticle) add("content-type", titleCase(contentType))
  if (topic) add("topic", topic)
  if (genericArticle && classifications.length === 0) add("content-type", titleCase(contentType))
  if (language) add("language", language.toUpperCase())

  return classifications
}

export type ArticleCardTime = {
  relativeLabel: string
  accessibleLabel: string
  title: string
  dateTime: string | undefined
}

export function getArticleCardTime(
  value: string,
  dateBasis: ArticleSummary["dateBasis"],
  now = Date.now(),
): ArticleCardTime {
  const timestamp = Date.parse(value)
  const basisLabel = dateBasis === "published" ? "Published" : "Collected"
  if (!Number.isFinite(timestamp)) {
    return {
      relativeLabel: "Time unavailable",
      accessibleLabel: `${basisLabel} time unavailable`,
      title: `${basisLabel} time unavailable`,
      dateTime: undefined,
    }
  }

  const exactLabel = formatExactTime(timestamp)
  if (!exactLabel) {
    return {
      relativeLabel: "Time unavailable",
      accessibleLabel: `${basisLabel} time unavailable`,
      title: `${basisLabel} time unavailable`,
      dateTime: undefined,
    }
  }

  const relativeLabel = formatRelativeTime(timestamp, Number.isFinite(now) ? now : Date.now())
  const exactDescription = dateBasis === "published"
    ? `Exact publication time: ${exactLabel}`
    : `Exact collection time: ${exactLabel}; publication time unavailable`

  return {
    relativeLabel,
    accessibleLabel: `${basisLabel} ${relativeLabel}. ${exactDescription}`,
    title: dateBasis === "published"
      ? `Published ${exactLabel}`
      : `Collected ${exactLabel} (publication time unavailable)`,
    dateTime: value,
  }
}

function normalize(value: string) {
  return value.trim().replace(/\s+/g, " ").toLocaleLowerCase("en-US")
}

function formatExactTime(timestamp: number) {
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(timestamp))
  } catch {
    return null
  }
}

function formatRelativeTime(timestamp: number, now: number) {
  const difference = timestamp - now
  const absoluteDifference = Math.abs(difference)
  if (absoluteDifference < 60_000) return "just now"

  const units: Array<{ unit: Intl.RelativeTimeFormatUnit; milliseconds: number; until: number }> = [
    { unit: "minute", milliseconds: 60_000, until: 60 * 60_000 },
    { unit: "hour", milliseconds: 60 * 60_000, until: 24 * 60 * 60_000 },
    { unit: "day", milliseconds: 24 * 60 * 60_000, until: 7 * 24 * 60 * 60_000 },
    { unit: "week", milliseconds: 7 * 24 * 60 * 60_000, until: 30 * 24 * 60 * 60_000 },
    { unit: "month", milliseconds: 30 * 24 * 60 * 60_000, until: 365 * 24 * 60 * 60_000 },
    { unit: "year", milliseconds: 365 * 24 * 60 * 60_000, until: Infinity },
  ]
  const selected = units.find((candidate) => absoluteDifference < candidate.until) ?? units.at(-1)!
  const amount = Math.round(difference / selected.milliseconds)
  return new Intl.RelativeTimeFormat("en-US", { numeric: "always" }).format(amount, selected.unit)
}
