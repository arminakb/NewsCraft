export type SourceStatus = "healthy" | "degraded" | "broken" | "disabled" | "unknown"
export type SourcePlatform = "rss" | "atom" | "telegram_public" | "google_news" | "gdelt" | "hackernews" | "unknown"

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
}

export type IngestionRunSummary = {
  id: string
  label: string
  scope: string
  status: "succeeded" | "partial" | "failed"
  progress: number
  duration: string
  items: number
}

export type ContentQueueItem = {
  id: string
  title: string
  summary?: string | null
  canonicalUrl?: string | null
  thumbnailUrl: string | null
  primaryMedia?: {
    src: string | null
    quality: string | null
    fetchStatus: string | null
  } | null
  sourceName: string
  sourcePlatform: SourcePlatform
  category: string
  language: string
  age: string
  status: string
  score?: number
  tags?: string[]
  contentType?: string | null
  rewriteBucket?: string | null
  isRewriteReady?: boolean | null
  rewriteReadyReason?: string | null
  rewriteBlockers?: string[]
  classificationReasons?: string[]
  sourceTier?: string | null
  freshnessBucket?: string | null
  qualityStatus?: string | null
  scoreBreakdown?: Record<string, unknown>
  contentText?: string | null
  direction?: "ltr" | "rtl" | null
  authors?: string[]
  publishedAt?: string | null
}

export type MediaTile = {
  id: string
  src: string
  format: string
  dimensions: string
  fileName: string
  age: string
  size: string
  fetchStatus?: string | null
  quality?: string | null
  confidence?: string | null
  isPrimaryCandidate?: boolean | null
  isPrimary?: boolean | null
  sourceType?: string | null
  role?: string | null
}

export type DashboardSnapshot = {
  counts: DashboardCounts
  sources: SourceSummary[]
  runs: IngestionRunSummary[]
  queue: ContentQueueItem[]
  media: MediaTile[]
}

export type DashboardCounts = {
  rssFeeds: number
  telegramChannels: number
  contentItems: number
  mediaAssets: number
  warnings: number
}

export type DiagnosticsSnapshot = {
  status: string
  checks: Record<string, string>
  sourceHealth: Record<string, number>
  problemSources: Array<Record<string, unknown>>
}
