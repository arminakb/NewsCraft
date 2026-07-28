export type SourceStatus = "healthy" | "degraded" | "broken" | "disabled" | "unknown"

export type SourcePlatform =
  | "rss"
  | "atom"
  | "telegram_public"
  | "google_news"
  | "gdelt"
  | "hackernews"
  | "unknown"

export type SourceSummary = {
  id: string
  platform: SourcePlatform
  name: string
  url: string
  category: string
  language: string
  status: SourceStatus
  items24h: number
  new24h: number
  failed24h: number
  lastSuccess: string | null
  fetchIntervalMinutes: number
  totalItems: number
  media24h: number
  addedAt: string
  lastCheckedAt?: string | null
  failureReason?: string | null
}

export type SourceHealthResult = {
  sourceId: string
  status: SourceStatus
  isChecking: boolean
  lastCheckedAt: string
  failureReason: string | null
}

export type CreateSourceInput = {
  platform: "rss" | "telegram_public"
  name: string
  url: string
  category: string
  language: string
  fetchIntervalMinutes: number
}
