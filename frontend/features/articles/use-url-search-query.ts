"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

import { normalizeArticleSearch, writeArticleSearch } from "./filter-state"

const SEARCH_COMMIT_DELAY_MS = 300

/**
 * Owns the article search box end to end: the draft the operator is typing,
 * the debounce before it reaches the URL, and the single write that commits
 * it.
 *
 * The URL is the only source of truth. `committedQuery` is read from the
 * router by the caller, so any other navigation — Back/Forward, a filter
 * change, a collection switch — resets the draft on its own; and the commit
 * goes through `router.push` like every other navigation on the page, which
 * keeps Next aware of the history entry it creates (a raw
 * `window.history.pushState` here is what previously forced a popstate
 * listener and two arbitration timers to exist).
 */
export function useUrlSearchQuery({
  committedQuery,
  debounceMs = SEARCH_COMMIT_DELAY_MS,
}: {
  committedQuery: string
  debounceMs?: number
}) {
  const router = useRouter()
  const pathname = usePathname()
  const search = useSearchParams().toString()
  const [draft, setDraft] = useState({ value: committedQuery, committedQuery })
  // Whenever the URL moves underneath an unsent draft, the URL wins.
  const value = draft.committedQuery === committedQuery ? draft.value : committedQuery

  useEffect(() => {
    const normalized = normalizeArticleSearch(value)
    if (normalized === committedQuery) return
    const timer = window.setTimeout(() => {
      const params = writeArticleSearch(new URLSearchParams(search), normalized)
      const queryString = params.toString()
      router.push(`${pathname}${queryString ? `?${queryString}` : ""}`, { scroll: false })
    }, debounceMs)
    return () => window.clearTimeout(timer)
  }, [committedQuery, debounceMs, pathname, router, search, value])

  const change = useCallback(
    (next: string) => setDraft({ value: next, committedQuery }),
    [committedQuery],
  )

  return { value, change }
}
