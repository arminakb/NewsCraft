export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value)
}

export function formatPlatform(platform: string) {
  if (platform === "telegram_public") {
    return "Telegram"
  }
  return "RSS"
}

export function titleCase(value: string) {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

export function formatBytes(value: number | null | undefined) {
  if (!value) {
    return "0 KB"
  }
  if (value < 1024 * 1024) {
    return `${Math.max(1, Math.round(value / 1024))} KB`
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
