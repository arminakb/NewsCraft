import { formatPlatform } from "@/lib/format"

describe("formatPlatform", () => {
  it.each([
    ["rss", "RSS"],
    ["atom", "Atom"],
    ["telegram_public", "Telegram"],
    ["google_news", "Google News"],
    ["gdelt", "GDELT"],
    ["hackernews", "Hacker News"],
    ["unknown", "Unknown"],
  ])("formats %s as %s", (platform, expected) => {
    expect(formatPlatform(platform)).toBe(expected)
  })
})
