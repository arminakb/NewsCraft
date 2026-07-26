export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value)
}

export function formatPlatform(platform: string) {
  switch (platform) {
    case "rss":
      return "RSS"
    case "atom":
      return "Atom"
    case "telegram_public":
      return "Telegram"
    case "google_news":
      return "Google News"
    case "gdelt":
      return "GDELT"
    case "hackernews":
      return "Hacker News"
    default:
      return "Unknown"
  }
}

export function titleCase(value: string) {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}
