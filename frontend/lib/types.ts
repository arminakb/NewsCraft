export type SourceStatus = "healthy" | "partial" | "failed"
export type SourcePlatform = "rss" | "telegram_public"

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
  nextRun: string | null
  totalItems: number
  media24h: number
  addedAt: string
  parser: string
  deduplication: string
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
  thumbnailUrl: string | null
  sourceName: string
  sourcePlatform: SourcePlatform
  category: string
  language: string
  age: string
  status: "new" | "queued"
}

export type MediaTile = {
  id: string
  src: string
  format: string
  dimensions: string
  fileName: string
  age: string
  size: string
}

export type DashboardSnapshot = {
  counts: {
    rssFeeds: number
    telegramChannels: number
    contentItems: number
    mediaAssets: number
    warnings: number
  }
  sources: SourceSummary[]
  runs: IngestionRunSummary[]
  queue: ContentQueueItem[]
  media: MediaTile[]
}
