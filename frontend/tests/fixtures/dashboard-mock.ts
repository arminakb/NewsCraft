import type { SourceSummary } from "@/features/operations/ingestion-types"

export const dashboardMock: {
  sources: SourceSummary[]
} = {
  sources: [
    {
      id: "rss_5f8d3c1a",
      platform: "rss",
      name: "TechCrunch",
      url: "https://techcrunch.com/feed/",
      category: "AI, Tech",
      language: "en",
      status: "healthy",
      items24h: 128,
      new24h: 42,
      failed24h: 0,
      lastSuccess: "09:28",
      fetchIntervalMinutes: 30,
      totalItems: 8612,
      media24h: 76,
      addedAt: "2024-11-12 14:22",
    },
    {
      id: "telegram_dw_persian",
      platform: "telegram_public",
      name: "DW Persian",
      url: "https://t.me/dw_farsi",
      category: "World",
      language: "fa",
      status: "degraded",
      items24h: 67,
      new24h: 18,
      failed24h: 2,
      lastSuccess: "09:10",
      fetchIntervalMinutes: 30,
      totalItems: 3920,
      media24h: 44,
      addedAt: "2025-01-08 08:40",
    },
  ],
}
