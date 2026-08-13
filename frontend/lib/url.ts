/**
 * Single scheme allowlist for URLs that reach an `href` or a backend payload.
 * Everything that is not absolute http(s) — `javascript:`, `data:`, relative
 * paths, garbage — collapses to null, and embedded credentials are rejected so
 * a rendered link can never leak a userinfo component.
 */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    if (url.protocol !== "http:" && url.protocol !== "https:") return null
    if (url.username || url.password) return null
    return url.href
  } catch {
    return null
  }
}
