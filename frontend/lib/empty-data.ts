import type { DashboardCounts, DashboardSnapshot } from "./types"

export const emptyDashboardCounts: DashboardCounts = {
  rssFeeds: 0,
  telegramChannels: 0,
  contentItems: 0,
  mediaAssets: 0,
  warnings: 0,
}

export const emptyDashboardSnapshot: DashboardSnapshot = {
  counts: emptyDashboardCounts,
  sources: [],
  runs: [],
  queue: [],
  media: [],
}
