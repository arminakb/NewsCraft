"use client"

import { type QueryClient, type QueryKey, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import type { ArticlePage } from "./types"

import { queryKeys } from "@/lib/query-keys"

export const ARTICLE_PAGE_STALE_TIME = 15_000
export const ARTICLE_PAGE_GC_TIME = 120_000

type ArticleCursorStore = Map<number, string | null>
export type ArticlePageFetcher = (cursor: string | null, signal?: AbortSignal) => Promise<ArticlePage>

/**
 * Walk forward from the nearest known page until `targetPage` has a cursor,
 * recording every cursor discovered on the way. Returns the furthest page that
 * actually exists, which may be earlier than the target when the feed ended.
 */
async function resolveArticlePageCursor({
  targetPage,
  currentPage,
  cursors,
  queryClient,
  queryKeyFor,
  fetchPage,
  pageSize,
}: {
  targetPage: number
  currentPage: number
  cursors: ArticleCursorStore
  queryClient: QueryClient
  queryKeyFor: (page: number, cursor: string | null) => QueryKey
  fetchPage: ArticlePageFetcher
  pageSize: number
}): Promise<{ page: number; cursor: string | null }> {
  if (targetPage <= 1) return { page: 1, cursor: null }
  if (cursors.has(targetPage)) return { page: targetPage, cursor: cursors.get(targetPage) ?? null }

  let startPage = 1
  for (const knownPage of cursors.keys()) {
    if (knownPage < targetPage && knownPage > startPage) startPage = knownPage
  }

  let cursor = cursors.get(startPage) ?? null
  for (let page = startPage; page < targetPage; page += 1) {
    if (cursors.has(page + 1)) {
      cursor = cursors.get(page + 1) ?? null
      continue
    }

    const pageKey = queryKeyFor(page, cursor)
    const result = await queryClient.fetchQuery({
      queryKey: pageKey,
      queryFn: ({ signal }) => fetchPage(cursor, signal),
      staleTime: ARTICLE_PAGE_STALE_TIME,
      gcTime: ARTICLE_PAGE_GC_TIME,
    })
    if (!result.nextCursor) {
      const lastPage = Math.max(1, Math.ceil(result.resultCount / pageSize))
      if (lastPage <= page) return { page: lastPage, cursor: cursors.get(lastPage) ?? cursor }
      return { page, cursor }
    }

    cursors.set(page + 1, result.nextCursor)
    cursor = result.nextCursor
    if (page !== currentPage) {
      queryClient.removeQueries({ queryKey: pageKey, exact: true, type: "inactive" })
    }
  }

  return { page: targetPage, cursor: cursors.get(targetPage) ?? cursor }
}

/**
 * The whole cursor↔page-number bridge for the article feed: the per-identity
 * cursor map, the page query itself, forward resolution of an unknown page,
 * neighbour prefetching and cache eviction. The caller supplies the URL facts
 * (`currentPage`, `urlCursor`), how to fetch and key a page, and how to
 * navigate — everything else stays inside here.
 */
export function useCursorPagination({
  identity,
  currentPage,
  urlCursor,
  pageSize,
  enabled,
  suspended,
  isSelectionGone,
  fetchPage,
  queryKeyFor,
  navigateToPage,
}: {
  identity: string
  currentPage: number
  urlCursor: string | null
  pageSize: number
  /** The selection is known and fetchable (a collection filter has resolved). */
  enabled: boolean
  /** The selection is known to be unavailable, so nothing should be resolved. */
  suspended: boolean
  /** Reads a page-query error as "the selected collection no longer exists". */
  isSelectionGone: (error: unknown) => boolean
  fetchPage: ArticlePageFetcher
  queryKeyFor: (page: number, cursor: string | null) => QueryKey
  navigateToPage: (page: number, cursor: string | null) => void
}) {
  const queryClient = useQueryClient()
  const [pendingPage, setPendingPage] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [resolving, setResolving] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const navigationRequestRef = useRef(0)

  // One cursor map per query identity. Deriving it here keeps the render
  // pure: the map is created, never mutated, while rendering, and every
  // write happens from an effect below.
  const cursors = useMemo<ArticleCursorStore>(() => new Map([[1, null]]), [identity])
  useEffect(() => {
    if (currentPage > 1 && urlCursor) cursors.set(currentPage, urlCursor)
  }, [currentPage, cursors, urlCursor])

  const cursor = currentPage === 1 ? null : urlCursor ?? cursors.get(currentPage)
  const cursorResolved = currentPage === 1 || cursor !== undefined
  const queryCursor = cursor ?? null

  const query = useQuery({
    queryKey: queryKeyFor(currentPage, queryCursor),
    queryFn: ({ signal }) => fetchPage(queryCursor, signal),
    enabled: enabled && cursorResolved,
    staleTime: ARTICLE_PAGE_STALE_TIME,
    gcTime: ARTICLE_PAGE_GC_TIME,
  })
  const resultCount = query.data?.resultCount
  const totalPages = resultCount === undefined ? 0 : Math.max(1, Math.ceil(resultCount / pageSize))
  const selectionGone = isSelectionGone(query.error)
  const blocked = suspended || selectionGone

  const resolve = useCallback((targetPage: number) => resolveArticlePageCursor({
    targetPage,
    currentPage,
    cursors,
    queryClient,
    queryKeyFor,
    fetchPage,
    pageSize,
  }), [currentPage, cursors, fetchPage, pageSize, queryClient, queryKeyFor])

  // The page number arrived from the URL without a usable cursor: walk forward
  // until it has one, then correct the URL if the feed ended earlier.
  useEffect(() => {
    if (!enabled || blocked || cursorResolved) return
    let active = true
    setResolving(true)
    setError(null)
    void resolve(currentPage).then(({ page, cursor: resolvedCursor }) => {
      if (!active) return
      cursors.set(page, resolvedCursor)
      setResolving(false)
      if (page !== currentPage) navigateToPage(page, resolvedCursor)
    }).catch((cause: unknown) => {
      if (!active) return
      setResolving(false)
      setError(cause)
    })
    return () => {
      active = false
    }
  }, [attempt, blocked, currentPage, cursorResolved, cursors, enabled, navigateToPage, resolve])

  useEffect(() => {
    setPendingPage(null)
    setError(null)
    navigationRequestRef.current += 1
  }, [identity, currentPage])

  // Record what the delivered page taught us about its neighbours.
  useEffect(() => {
    if (query.data === undefined || !cursorResolved) return
    cursors.set(currentPage, queryCursor)
    if (query.data.nextCursor) {
      cursors.set(currentPage + 1, query.data.nextCursor)
    } else {
      for (const page of cursors.keys()) {
        if (page > currentPage) cursors.delete(page)
      }
    }
  }, [currentPage, cursorResolved, cursors, query.data, queryCursor])

  useEffect(() => {
    if (query.data === undefined || resultCount === undefined || !cursorResolved) return
    const prefetches: Promise<unknown>[] = []
    if (query.data.nextCursor && currentPage < totalPages) {
      const nextPage = currentPage + 1
      cursors.set(nextPage, query.data.nextCursor)
      prefetches.push(queryClient.prefetchQuery({
        queryKey: queryKeyFor(nextPage, query.data.nextCursor),
        queryFn: ({ signal }) => fetchPage(query.data.nextCursor as string, signal),
        staleTime: ARTICLE_PAGE_STALE_TIME,
        gcTime: ARTICLE_PAGE_GC_TIME,
      }))
    }
    const previousCursor = currentPage > 1 ? cursors.get(currentPage - 1) : undefined
    if (currentPage > 1 && previousCursor !== undefined) {
      prefetches.push(queryClient.prefetchQuery({
        queryKey: queryKeyFor(currentPage - 1, previousCursor),
        queryFn: ({ signal }) => fetchPage(previousCursor, signal),
        staleTime: ARTICLE_PAGE_STALE_TIME,
        gcTime: ARTICLE_PAGE_GC_TIME,
      }))
    }
    void Promise.allSettled(prefetches)
  }, [currentPage, cursorResolved, cursors, fetchPage, query.data, queryClient, queryKeyFor, queryCursor, resultCount, totalPages])

  useEffect(() => {
    queryClient.removeQueries({
      queryKey: queryKeys.articlePages,
      type: "inactive",
      predicate: (cachedQuery) => {
        const params = cachedQuery.queryKey[2]
        if (!params || typeof params !== "object") return false
        const cached = params as { identity?: unknown; page?: unknown }
        if (cached.identity !== identity || typeof cached.page !== "number") return cached.identity !== identity
        return Math.abs(cached.page - currentPage) > 1
      },
    })
  }, [currentPage, identity, queryClient])

  const requestPage = useCallback((targetPage: number) => {
    if (targetPage < 1 || targetPage === currentPage || pendingPage !== null || targetPage > totalPages) return
    if (targetPage === 1 || cursors.has(targetPage)) {
      setError(null)
      navigateToPage(targetPage, targetPage === 1 ? null : cursors.get(targetPage) ?? null)
      return
    }

    const requestId = navigationRequestRef.current + 1
    navigationRequestRef.current = requestId
    setPendingPage(targetPage)
    setError(null)
    void resolve(targetPage).then(({ page, cursor: resolvedCursor }) => {
      if (navigationRequestRef.current !== requestId) return
      setPendingPage(null)
      navigateToPage(page, resolvedCursor)
    }).catch((cause: unknown) => {
      if (navigationRequestRef.current !== requestId) return
      setError(cause)
      setPendingPage(null)
    })
  }, [currentPage, cursors, navigateToPage, pendingPage, resolve, totalPages])

  const retry = useCallback(() => {
    setError(null)
    setAttempt((value) => value + 1)
  }, [])

  const resetCursors = useCallback(() => {
    cursors.clear()
    cursors.set(1, null)
  }, [cursors])

  return {
    error,
    pendingPage,
    query,
    requestPage,
    resetCursors,
    resolving,
    resultCount,
    retry,
    selectionGone,
    totalPages,
  }
}
