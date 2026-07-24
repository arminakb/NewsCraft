import { getArticleCardClassifications, getArticleCardTime } from "@/features/articles/article-card-metadata"

describe("article card metadata", () => {
  it("replaces generic Article with the more useful News topic", () => {
    expect(labels({ contentType: "article", topic: "News", language: "en" })).toEqual(["News", "EN"])
  })

  it("deduplicates labels case-insensitively after display formatting", () => {
    expect(labels({ contentType: "news", topic: "NEWS", language: "fa" })).toEqual(["News", "FA"])
    expect(labels({ contentType: "breaking_news", topic: "Breaking News", language: "en" }))
      .toEqual(["Breaking News", "EN"])
  })

  it("keeps a specific content type, distinct topic, and language in priority order", () => {
    expect(getArticleCardClassifications({ contentType: "analysis", topic: "Economy", language: "fa" }))
      .toEqual([
        { kind: "content-type", label: "Analysis" },
        { kind: "topic", label: "Economy" },
        { kind: "language", label: "FA" },
      ])
  })

  it("keeps generic Article only when no topic is more useful", () => {
    expect(labels({ contentType: "ARTICLE", topic: null, language: "en" })).toEqual(["ARTICLE", "EN"])
  })
})

describe("article card relative time", () => {
  const now = Date.parse("2026-07-22T12:00:00Z")

  it.each([
    ["2026-07-22T08:00:00Z", "4 hours ago"],
    ["2026-07-21T12:00:00Z", "1 day ago"],
    ["2026-07-01T12:00:00Z", "3 weeks ago"],
    ["2026-05-23T12:00:00Z", "2 months ago"],
  ])("formats %s as %s", (value, expected) => {
    expect(getArticleCardTime(value, "published", now).relativeLabel).toBe(expected)
  })

  it("exposes collection basis and the exact timestamp accessibly", () => {
    const time = getArticleCardTime("2026-07-21T12:00:00Z", "collected", now)

    expect(time.relativeLabel).toBe("1 day ago")
    expect(time.title).toMatch(/^Collected .+ \(publication time unavailable\)$/)
    expect(time.accessibleLabel).toContain("Exact collection time:")
    expect(time.accessibleLabel).toContain("publication time unavailable")
  })

  it("falls back safely for invalid and future timestamps", () => {
    expect(getArticleCardTime("not-a-date", "published", now)).toEqual({
      relativeLabel: "Time unavailable",
      accessibleLabel: "Published time unavailable",
      title: "Published time unavailable",
      dateTime: undefined,
    })
    expect(getArticleCardTime("2026-07-22T14:00:00Z", "published", now).relativeLabel).toBe("in 2 hours")
  })
})

function labels(input: { contentType: string; topic: string | null; language: string | null }) {
  return getArticleCardClassifications(input).map((item) => item.label)
}
