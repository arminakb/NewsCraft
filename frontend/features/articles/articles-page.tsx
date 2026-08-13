"use client"

import { type QueryClient, type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bookmark, ExternalLink, Gauge, ImageIcon, LoaderCircle, Search, Trash2, X } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { ActiveFilterChips, ArticleFilterControl } from "./article-filter-control"
import { ArticlePagination } from "./article-pagination"
import { ArticleDetailDialog } from "./article-detail-dialog"
import { getArticleCardClassifications, getArticleCardTime } from "./article-card-metadata"
import { clearFeed, getArticleCollections, getArticleFacets, getArticles, getFeedSummary, removeArticleFromCollection } from "./api"
import { CollectionsSidebar } from "./collections-sidebar"
import {
  EMPTY_ARTICLE_FILTERS,
  activeFilterCount,
  filtersEqual,
  readArticleCursor,
  readArticlePage,
  readArticleState,
  writeArticleState,
} from "./filter-state"
import { SaveToCollectionDialog } from "./save-to-collection-dialog"
import { useUrlSearchQuery } from "./use-url-search-query"
import type { ArticleCollection, ArticleImage, ArticlePage, ArticleSort, ArticleSummary, FeedSummary } from "./types"

import { EditorialDialog } from "@/components/editorial/editorial-dialog"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/ui/page-header"
import { Select } from "@/components/ui/select"
import { EmptyState, ErrorState } from "@/components/ui/state-panel"
import { formatNumber } from "@/lib/format"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { safeHttpUrl } from "@/lib/url"

const PAGE_SIZE = 50
const ARTICLE_PAGE_STALE_TIME = 15_000
const ARTICLE_PAGE_GC_TIME = 120_000

type ArticleCursorStore = Map<number, string | null>
type ArticlePageFetcher = (cursor: string | null, signal?: AbortSignal) => Promise<ArticlePage>

async function resolveArticlePageCursor({
  targetPage,
  currentPage,
  cursors,
  queryClient,
  queryKeyFor,
  fetchPage,
}: {
  targetPage: number
  currentPage: number
  cursors: ArticleCursorStore
  queryClient: QueryClient
  queryKeyFor: (page: number, cursor: string | null) => QueryKey
  fetchPage: ArticlePageFetcher
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
      const lastPage = Math.max(1, Math.ceil(result.resultCount / PAGE_SIZE))
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

export function ArticlesPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { timezone } = useDateTime()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const search = searchParams.toString()
  const {
    sort,
    filters,
    query: titleQuery,
    collectionId,
    currentPage,
    urlCursor,
  } = useMemo(() => {
    const params = new URLSearchParams(search)
    return {
      ...readArticleState(params),
      collectionId: params.get("collection_id"),
      currentPage: readArticlePage(params),
      urlCursor: readArticleCursor(params),
    }
  }, [search])
  const filterCount = activeFilterCount(filters)
  const [announcement, setAnnouncement] = useState("")
  const [savingArticle, setSavingArticle] = useState<ArticleSummary | null>(null)
  const [detailArticle, setDetailArticle] = useState<ArticleSummary | null>(null)
  const [membershipPending, setMembershipPending] = useState(false)
  const [directRemovalPendingId, setDirectRemovalPendingId] = useState<string | null>(null)
  const [directRemovalError, setDirectRemovalError] = useState<{ article: ArticleSummary; message: string } | null>(null)
  const [focusAllFeedToken, setFocusAllFeedToken] = useState(0)
  const [pendingPage, setPendingPage] = useState<number | null>(null)
  const [pageResolutionError, setPageResolutionError] = useState<unknown>(null)
  const [pageResolutionPending, setPageResolutionPending] = useState(false)
  const [pageResolutionAttempt, setPageResolutionAttempt] = useState(0)
  const [clearFeedOpen, setClearFeedOpen] = useState(false)
  const { value: searchDraft, change: changeSearchDraft } = useUrlSearchQuery({ committedQuery: titleQuery })
  const directRemovalBusyRef = useRef(false)
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null)
  const pageNavigationRequestRef = useRef(0)
  const collectionsQuery = useQuery({
    queryKey: queryKeys.articleCollections,
    queryFn: ({ signal }) => getArticleCollections(signal),
  })
  const feedSummaryQuery = useQuery({
    queryKey: queryKeys.feedSummary,
    queryFn: ({ signal }) => getFeedSummary(signal),
    staleTime: 15_000,
  })
  const clearFeedMutation = useMutation({ mutationFn: clearFeed })
  const selectedCollection = collectionsQuery.data?.find((collection) => collection.id === collectionId)
  const missingFromList = Boolean(collectionId && collectionsQuery.isSuccess && !selectedCollection)
  const selectedCollectionId = selectedCollection?.id ?? null
  const queryEnabled = collectionId === null || Boolean(selectedCollection)
  const articleQueryIdentity = useMemo(() => JSON.stringify({
    sort,
    filters,
    titleQuery,
    collectionId: selectedCollectionId,
    timezone,
  }), [filters, selectedCollectionId, sort, timezone, titleQuery])
  // One cursor map per query identity. Deriving it here keeps the render
  // pure: the map is created, never mutated, while rendering, and every
  // write happens from an effect below.
  const cursorStore = useMemo<ArticleCursorStore>(
    () => new Map([[1, null]]),
    [articleQueryIdentity],
  )
  useEffect(() => {
    if (currentPage > 1 && urlCursor) cursorStore.set(currentPage, urlCursor)
  }, [currentPage, cursorStore, urlCursor])
  const currentCursor = currentPage === 1
    ? null
    : urlCursor ?? cursorStore.get(currentPage)
  const pageCursorResolved = currentPage === 1 || currentCursor !== undefined
  const facetsQuery = useQuery({
    queryKey: queryKeys.articleFacets,
    queryFn: getArticleFacets,
    staleTime: Infinity,
  })
  const fetchArticlePage = useCallback((cursor: string | null, signal?: AbortSignal) => getArticles({
      sort,
      ...(titleQuery ? { query: titleQuery } : {}),
      filters,
      ...(selectedCollectionId ? { collectionId: selectedCollectionId } : {}),
      cursor,
      limit: PAGE_SIZE,
      timezone,
    }, signal), [filters, selectedCollectionId, sort, timezone, titleQuery])
  const queryKeyFor = useCallback((page: number, cursor: string | null) => queryKeys.articlePage({
    identity: articleQueryIdentity,
    sort,
    filters,
    query: titleQuery,
    collectionId: selectedCollectionId,
    page,
    cursor,
  }), [articleQueryIdentity, filters, selectedCollectionId, sort, titleQuery])
  const queryCursor = currentCursor ?? null
  const query = useQuery({
    queryKey: queryKeyFor(currentPage, queryCursor),
    queryFn: ({ signal }) => fetchArticlePage(queryCursor, signal),
    enabled: queryEnabled && pageCursorResolved,
    staleTime: ARTICLE_PAGE_STALE_TIME,
    gcTime: ARTICLE_PAGE_GC_TIME,
  })
  const articles = query.data?.items ?? []
  const resultCount = query.data?.resultCount
  const totalPages = resultCount === undefined ? 0 : Math.max(1, Math.ceil(resultCount / PAGE_SIZE))
  const collectionDeleted = Boolean(collectionId && query.error instanceof ApiError && query.error.status === 404)
  const unavailableSelection = missingFromList || collectionDeleted

  const navigateToPage = useCallback((nextPage: number, nextCursor: string | null) => {
    const params = new URLSearchParams(search)
    if (nextPage <= 1) {
      params.delete("page")
      params.delete("cursor")
    } else {
      params.set("page", String(nextPage))
      if (nextCursor) params.set("cursor", nextCursor)
      else params.delete("cursor")
    }
    const queryString = params.toString()
    router.push(`${pathname}${queryString ? `?${queryString}` : ""}`, { scroll: false })
  }, [pathname, router, search])

  const resolvePage = useCallback((targetPage: number) => resolveArticlePageCursor({
    targetPage,
    currentPage,
    cursors: cursorStore,
    queryClient,
    queryKeyFor,
    fetchPage: fetchArticlePage,
  }), [currentPage, cursorStore, fetchArticlePage, queryClient, queryKeyFor])

  useEffect(() => {
    if (!queryEnabled || unavailableSelection || pageCursorResolved) return
    let active = true
    setPageResolutionPending(true)
    setPageResolutionError(null)
    void resolvePage(currentPage).then(({ page, cursor }) => {
      if (!active) return
      cursorStore.set(page, cursor)
      setPageResolutionPending(false)
      if (page !== currentPage) {
        navigateToPage(page, cursor)
      }
    }).catch((cause: unknown) => {
      if (!active) return
      setPageResolutionPending(false)
      setPageResolutionError(cause)
    })
    return () => {
      active = false
    }
  }, [currentPage, cursorStore, navigateToPage, pageCursorResolved, queryEnabled, resolvePage, unavailableSelection, pageResolutionAttempt])

  useEffect(() => {
    setPendingPage(null)
    setPageResolutionError(null)
    pageNavigationRequestRef.current += 1
  }, [articleQueryIdentity, currentPage])

  useEffect(() => {
    if (query.data === undefined || !pageCursorResolved) return
    cursorStore.set(currentPage, queryCursor)
    if (query.data.nextCursor) {
      cursorStore.set(currentPage + 1, query.data.nextCursor)
    } else {
      for (const page of cursorStore.keys()) {
        if (page > currentPage) cursorStore.delete(page)
      }
    }
  }, [currentPage, cursorStore, pageCursorResolved, query.data, queryCursor])

  useEffect(() => {
    if (query.data === undefined || resultCount === undefined || !pageCursorResolved) return
    const prefetches: Promise<unknown>[] = []
    if (query.data.nextCursor && currentPage < totalPages) {
      const nextPage = currentPage + 1
      cursorStore.set(nextPage, query.data.nextCursor)
      prefetches.push(queryClient.prefetchQuery({
        queryKey: queryKeyFor(nextPage, query.data.nextCursor),
        queryFn: ({ signal }) => fetchArticlePage(query.data.nextCursor as string, signal),
        staleTime: ARTICLE_PAGE_STALE_TIME,
        gcTime: ARTICLE_PAGE_GC_TIME,
      }))
    }
    const previousCursor = currentPage > 1 ? cursorStore.get(currentPage - 1) : undefined
    if (currentPage > 1 && previousCursor !== undefined) {
      prefetches.push(queryClient.prefetchQuery({
        queryKey: queryKeyFor(currentPage - 1, previousCursor),
        queryFn: ({ signal }) => fetchArticlePage(previousCursor, signal),
        staleTime: ARTICLE_PAGE_STALE_TIME,
        gcTime: ARTICLE_PAGE_GC_TIME,
      }))
    }
    void Promise.allSettled(prefetches)
  }, [currentPage, cursorStore, fetchArticlePage, pageCursorResolved, query.data, queryClient, queryKeyFor, queryCursor, resultCount, totalPages])

  useEffect(() => {
    queryClient.removeQueries({
      queryKey: queryKeys.articlePages,
      type: "inactive",
      predicate: (cachedQuery) => {
        const params = cachedQuery.queryKey[2]
        if (!params || typeof params !== "object") return false
        const cached = params as { identity?: unknown; page?: unknown }
        if (cached.identity !== articleQueryIdentity || typeof cached.page !== "number") return cached.identity !== articleQueryIdentity
        return Math.abs(cached.page - currentPage) > 1
      },
    })
  }, [articleQueryIdentity, currentPage, queryClient])

  const feedLocationRef = useRef<{ identity: string; page: number } | null>(null)
  useEffect(() => {
    const previous = feedLocationRef.current
    feedLocationRef.current = { identity: articleQueryIdentity, page: currentPage }
    if (!previous || (previous.identity === articleQueryIdentity && previous.page === currentPage)) return
    const scrollContainer = document.querySelector<HTMLElement>(".newsroom-scroll")
    if (!scrollContainer) return
    const reducedMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    if (typeof scrollContainer.scrollTo === "function") {
      scrollContainer.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" })
    } else {
      scrollContainer.scrollTop = 0
    }
  }, [articleQueryIdentity, currentPage])

  const navigate = useCallback((nextSort: ArticleSort, nextFilters: typeof filters) => {
    const params = writeArticleState(new URLSearchParams(search), nextSort, nextFilters)
    const queryString = params.toString()
    router.push(`${pathname}${queryString ? `?${queryString}` : ""}`, { scroll: false })
  }, [pathname, router, search])
  const changeFilters = (nextFilters: typeof filters) => {
    if (!filtersEqual(filters, nextFilters)) navigate(sort, nextFilters)
  }

  const requestPage = useCallback((targetPage: number) => {
    if (targetPage < 1 || targetPage === currentPage || pendingPage !== null || targetPage > totalPages) return
    if (targetPage === 1 || cursorStore.has(targetPage)) {
      setPageResolutionError(null)
      navigateToPage(targetPage, targetPage === 1 ? null : cursorStore.get(targetPage) ?? null)
      return
    }

    const requestId = pageNavigationRequestRef.current + 1
    pageNavigationRequestRef.current = requestId
    setPendingPage(targetPage)
    setPageResolutionError(null)
    void resolvePage(targetPage).then(({ page, cursor }) => {
      if (pageNavigationRequestRef.current !== requestId) return
      setPendingPage(null)
      navigateToPage(page, cursor)
    }).catch((cause: unknown) => {
      if (pageNavigationRequestRef.current !== requestId) return
      setPageResolutionError(cause)
      setPendingPage(null)
    })
  }, [currentPage, cursorStore, navigateToPage, pendingPage, resolvePage, totalPages])

  const selectCollection = useCallback((nextCollectionId: string | null) => {
    const params = new URLSearchParams(search)
    params.delete("page")
    params.delete("cursor")
    if (nextCollectionId) params.set("collection_id", nextCollectionId)
    else params.delete("collection_id")
    const queryString = params.toString()
    router.push(`${pathname}${queryString ? `?${queryString}` : ""}`, { scroll: false })
  }, [pathname, router, search])

  const handleCollectionCreated = useCallback((collection: ArticleCollection) => {
    queryClient.setQueryData<ArticleCollection[]>(queryKeys.articleCollections, (current = []) => (
      [...current.filter((item) => item.id !== collection.id), collection]
        .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }))
    ))
    void queryClient.invalidateQueries({ queryKey: queryKeys.articleCollections })
    setAnnouncement(`Collection ${collection.name} created and selected.`)
    selectCollection(collection.id)
  }, [queryClient, selectCollection])

  const handleInlineCollectionCreated = useCallback((collection: ArticleCollection) => {
    queryClient.setQueryData<ArticleCollection[]>(queryKeys.articleCollections, (current = []) => (
      [...current.filter((item) => item.id !== collection.id), collection]
        .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }))
    ))
    void queryClient.invalidateQueries({ queryKey: queryKeys.articleCollections })
    setAnnouncement(`Collection ${collection.name} created and selected in the Save dialog.`)
  }, [queryClient])

  const reconcileMemberships = useCallback(async (articleId: string, confirmedCollectionIds: string[]) => {
    const [articlesResult] = await Promise.all([
      query.refetch({ throwOnError: true }),
      collectionsQuery.refetch({ throwOnError: true }),
    ])
    const refreshedArticle = articlesResult.data?.items.find((article) => article.id === articleId)
    return refreshedArticle?.savedCollectionIds ?? confirmedCollectionIds
  }, [collectionsQuery, query])

  const handleCollectionRenamed = useCallback(async (collection: ArticleCollection) => {
    queryClient.setQueryData<ArticleCollection[]>(queryKeys.articleCollections, (current = []) => (
      [...current.filter((item) => item.id !== collection.id), collection]
        .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }))
    ))
    await collectionsQuery.refetch({ throwOnError: true })
    setAnnouncement(`Collection renamed to ${collection.name}.`)
  }, [collectionsQuery, queryClient])

  const handleCollectionDeleted = useCallback(async (collection: ArticleCollection) => {
    const wasSelected = collectionId === collection.id
    if (!wasSelected) await query.refetch({ throwOnError: true })
    await collectionsQuery.refetch({ throwOnError: true })
    if (wasSelected) selectCollection(null)
    setFocusAllFeedToken((current) => current + 1)
    setAnnouncement(`Collection ${collection.name} deleted. Articles remain in NewsCraft.`)
  }, [collectionId, collectionsQuery, query, selectCollection])

  const handleDirectRemoval = useCallback(async (article: ArticleSummary) => {
    if (!selectedCollection || directRemovalBusyRef.current) return
    directRemovalBusyRef.current = true
    setDirectRemovalPendingId(article.id)
    setDirectRemovalError(null)
    try {
      await removeArticleFromCollection(selectedCollection.id, article.id)
    } catch (cause) {
      await Promise.allSettled([
        query.refetch(),
        collectionsQuery.refetch(),
      ])
      setDirectRemovalError({
        article,
        message: getApiErrorMessage(cause, `Article could not be removed from ${selectedCollection.name}`),
      })
      directRemovalBusyRef.current = false
      setDirectRemovalPendingId(null)
      return
    }

    try {
      await Promise.all([
        query.refetch({ throwOnError: true }),
        collectionsQuery.refetch({ throwOnError: true }),
      ])
      setAnnouncement(`Article removed from ${selectedCollection.name}.`)
    } catch (cause) {
      setDirectRemovalError({
        article,
        message: getApiErrorMessage(cause, "Article was removed, but the Feed could not be refreshed. Retry to reconcile."),
      })
    } finally {
      directRemovalBusyRef.current = false
      setDirectRemovalPendingId(null)
    }
  }, [collectionsQuery, query, selectedCollection])

  const handleClearFeed = useCallback(async () => {
    try {
      const result = await clearFeedMutation.mutateAsync()
      const emptyPage: ArticlePage = { items: [], nextCursor: null, resultCount: 0 }
      queryClient.setQueriesData<ArticlePage>({ queryKey: queryKeys.articlePages }, (current) => (
        current ? { ...current, ...emptyPage } : current
      ))
      queryClient.setQueryData<FeedSummary>(queryKeys.feedSummary, { articleCount: 0 })
      cursorStore.clear()
      cursorStore.set(1, null)
      setClearFeedOpen(false)
      clearFeedMutation.reset()
      navigateToPage(1, null)
      setAnnouncement(result.clearedCount === 0
        ? "Feed was already empty."
        : `Feed cleared. ${formatNumber(result.clearedCount)} ${result.clearedCount === 1 ? "article" : "articles"} removed.`)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.articlePages }),
        queryClient.invalidateQueries({ queryKey: queryKeys.articleFacets }),
      ])
      queryClient.removeQueries({ queryKey: queryKeys.articlePages, type: "inactive" })
    } catch {
      // Keep the dialog open so the operator can retry or cancel.
    }
  }, [clearFeedMutation, cursorStore, navigateToPage, queryClient])

  const changeDetailOpen = useCallback((open: boolean) => {
    if (open) return
    setDetailArticle(null)
    window.requestAnimationFrame(() => detailTriggerRef.current?.focus())
  }, [])

  const openArticleDetails = useCallback((article: ArticleSummary, trigger: HTMLButtonElement) => {
    detailTriggerRef.current = trigger
    setDetailArticle(article)
  }, [])

  const saveFromDetails = useCallback((article: ArticleSummary) => {
    changeDetailOpen(false)
    window.requestAnimationFrame(() => setSavingArticle(article))
  }, [changeDetailOpen])

  return (
    <div className="min-w-0 min-[900px]:grid min-[900px]:grid-cols-[216px_minmax(0,1fr)] lg:grid-cols-[224px_minmax(0,1fr)]">
      <CollectionsSidebar
        collections={collectionsQuery.data}
        error={collectionsQuery.error}
        focusAllFeedToken={focusAllFeedToken}
        onCreated={handleCollectionCreated}
        onDeleted={handleCollectionDeleted}
        onRenamed={handleCollectionRenamed}
        onRetry={() => void collectionsQuery.refetch()}
        onSelect={selectCollection}
        pending={collectionsQuery.isPending}
        selectedId={collectionId}
      />
      <section className="feed-content nc-page mx-auto w-full max-w-[1600px]" aria-labelledby="feed-heading">
      <p aria-live="polite" className="sr-only" role="status">{announcement}</p>
      <PageHeader
        className="flex-col items-stretch sm:flex-row sm:items-end"
        title="Feed"
        titleId="feed-heading"
        description={resultCount === undefined
          ? "Loading result count…"
          : `${formatNumber(resultCount)} ${resultCount === 1 ? "article" : "articles"} · source monitoring and saved collections`}
        descriptionProps={{ "aria-live": "polite" }}
        actions={<div className="grid w-full min-w-0 grid-cols-2 items-end gap-2 sm:flex sm:w-auto sm:flex-wrap sm:justify-end">
          <label className="col-span-2 grid min-w-0 gap-1 text-xs font-medium text-muted-foreground sm:col-span-1">
            <span className="sr-only">Search articles</span>
            <span className="flex min-h-11 w-full items-center gap-2 rounded-lg border border-input bg-card px-3 transition-colors has-[:focus-visible]:border-ring sm:w-64 sm:min-h-9">
              <Search className="size-4 shrink-0" aria-hidden="true" />
              <input
                aria-label="Search articles"
                className="min-w-0 flex-1 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden sm:text-sm"
                dir="auto"
                onChange={(event) => changeSearchDraft(event.target.value)}
                placeholder="Search in articles"
                type="search"
                value={searchDraft}
              />
              {searchDraft ? (
                <button
                  aria-label="Clear search input"
                  className="inline-flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => changeSearchDraft("")}
                  type="button"
                >
                  <X className="size-4" aria-hidden="true" />
                </button>
              ) : null}
            </span>
          </label>
          <ArticleFilterControl
            facets={facetsQuery.data}
            facetsError={facetsQuery.error}
            facetsPending={facetsQuery.isPending}
            filters={filters}
            onApply={changeFilters}
            onClear={() => changeFilters(EMPTY_ARTICLE_FILTERS)}
            onRetryFacets={() => void facetsQuery.refetch()}
          />
          <label className="grid min-w-32 gap-1 text-xs font-medium text-muted-foreground">
            Sort by
            <Select
              aria-label="Sort articles"
              onChange={(event) => navigate(event.target.value as ArticleSort, filters)}
              value={sort}
            >
              <option value="newest">Newest</option>
              <option value="score">Score</option>
            </Select>
          </label>
          <Button
            className="col-span-2 sm:col-span-1"
            disabled={feedSummaryQuery.isPending || clearFeedMutation.isPending}
            onClick={() => {
              clearFeedMutation.reset()
              setClearFeedOpen(true)
              void feedSummaryQuery.refetch()
            }}
            type="button"
            variant="outline"
          >
            <Trash2 aria-hidden="true" />
            Clear Feed
          </Button>
        </div>}
      />

      {feedSummaryQuery.isError ? (
        <Alert role="alert" tone="error">
          <div className="flex items-center justify-between gap-3">
            <span>Feed count could not be loaded. Clear Feed is still available after a retry.</span>
            <Button className="shrink-0" onClick={() => void feedSummaryQuery.refetch()} size="sm" variant="outline">
              Retry count
            </Button>
          </div>
        </Alert>
      ) : null}

      <ActiveFilterChips
        filters={filters}
        facets={facetsQuery.data}
        onChange={changeFilters}
        onClear={() => changeFilters(EMPTY_ARTICLE_FILTERS)}
      />

      {unavailableSelection ? (
        <Card size="sm">
          <CardContent className="space-y-3 p-6">
            <div>
              <h2 className="font-semibold">Collection no longer available</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This collection may have been deleted in another session. Return to all articles to continue.
              </p>
            </div>
            <Button onClick={() => selectCollection(null)} variant="outline">Return to all articles</Button>
          </CardContent>
        </Card>
      ) : null}

      {!unavailableSelection && query.isPending && pageResolutionError === null ? <ArticleSkeletons /> : null}

      {!unavailableSelection && pageResolutionError !== null && articles.length === 0 ? (
        <ErrorState
          title="Feed page unavailable"
          description={getApiErrorMessage(pageResolutionError, "The requested Feed page could not be prepared")}
          action={<Button variant="outline" onClick={() => {
            setPageResolutionError(null)
            setPageResolutionAttempt((attempt) => attempt + 1)
          }}>Retry</Button>}
          dir="auto"
        />
      ) : null}

      {!unavailableSelection && query.isError && articles.length === 0 ? (
        <ErrorState
          title="Feed unavailable"
          description={getApiErrorMessage(query.error, "Articles could not be loaded")}
          action={<Button variant="outline" onClick={() => query.refetch()}>Retry</Button>}
          dir="auto"
        />
      ) : null}

      {!unavailableSelection && query.isSuccess && resultCount === 0 ? (
        <EmptyState
          icon={ImageIcon}
          title={titleQuery
                ? `No articles match “${titleQuery}”`
                : selectedCollection?.articleCount === 0
                ? `${selectedCollection.name} is empty`
                : filterCount
                  ? "No articles match these filters"
                  : "No articles collected"}
          description={titleQuery
                ? "Try a different article search or clear it."
                : selectedCollection?.articleCount === 0
                ? "Use Save to Collection on a Feed card to add articles here."
                : filterCount
                  ? "Try removing one or more filters."
                  : "New RSS and Telegram items will appear here."}
          action={titleQuery ? (
              <Button onClick={() => changeSearchDraft("")} variant="outline">Clear article search</Button>
            ) : filterCount && selectedCollection?.articleCount !== 0 ? (
              <Button onClick={() => changeFilters(EMPTY_ARTICLE_FILTERS)} variant="outline">Clear filters</Button>
            ) : null}
        />
      ) : null}

      {articles.length > 0 ? (
        <>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            Showing {formatNumber(articles.length)} of {formatNumber(resultCount ?? articles.length)} · Page {formatNumber(currentPage)} of {formatNumber(totalPages)}
          </p>
          <div
            className="feed-card-grid"
            aria-label="Feed results"
          >
            {articles.map((article) => (
              <ArticleCard
                article={article}
                key={article.id}
                collectionName={selectedCollection?.name ?? null}
                onSave={() => selectedCollection
                  ? void handleDirectRemoval(article)
                  : setSavingArticle(article)}
                onViewDetails={(trigger) => openArticleDetails(article, trigger)}
                savePending={(membershipPending && savingArticle?.id === article.id) || directRemovalPendingId === article.id}
              />
            ))}
          </div>

          {directRemovalError ? (
            <Alert tone="error" role="alert">
              <div className="flex items-center justify-between gap-3">
                <span dir="auto">{directRemovalError.message}</span>
                <Button
                  className="shrink-0"
                  disabled={directRemovalPendingId !== null}
                  onClick={() => void handleDirectRemoval(directRemovalError.article)}
                  size="sm"
                  variant="outline"
                >
                  Retry removal
                </Button>
              </div>
            </Alert>
          ) : null}

          {query.error ? (
            <Alert role="alert" dir="auto" tone="error">
              {getApiErrorMessage(query.error, "This Feed page could not be loaded")}
            </Alert>
          ) : null}

          {pageResolutionError !== null ? (
            <Alert role="alert" dir="auto" tone="error">
              <div className="flex items-center justify-between gap-3">
                <span>{getApiErrorMessage(pageResolutionError, "The requested Feed page could not be prepared")}</span>
                <Button
                  className="shrink-0"
                  onClick={() => {
                    setPageResolutionError(null)
                    setPageResolutionAttempt((attempt) => attempt + 1)
                  }}
                  size="sm"
                  variant="outline"
                >
                  Retry page
                </Button>
              </div>
            </Alert>
          ) : null}

          {totalPages > 1 ? (
            <div className="flex flex-col items-center gap-2 pb-20 pt-4">
              {(pendingPage !== null || pageResolutionPending) ? (
                <p aria-live="polite" className="text-xs text-muted-foreground" role="status">
                  Loading page {formatNumber(pendingPage ?? currentPage)}…
                </p>
              ) : null}
              <ArticlePagination
                currentPage={currentPage}
                disabled={pendingPage !== null || pageResolutionPending || query.isFetching}
                onPageChange={requestPage}
                totalPages={totalPages}
              />
            </div>
          ) : null}
        </>
      ) : null}

      <SaveToCollectionDialog
        article={savingArticle}
        collections={collectionsQuery.data}
        collectionsError={collectionsQuery.error}
        collectionsPending={collectionsQuery.isPending}
        onClose={() => setSavingArticle(null)}
        onCollectionCreated={handleInlineCollectionCreated}
        onPendingChange={setMembershipPending}
        onReconcile={reconcileMemberships}
        onRetryCollections={() => void collectionsQuery.refetch()}
        onSaved={(collectionCount) => {
          setAnnouncement(collectionCount === 0
            ? "Article removed from all collections."
            : `Article saved to ${collectionCount} ${collectionCount === 1 ? "collection" : "collections"}.`)
        }}
        open={savingArticle !== null}
      />
      <ArticleDetailDialog
        article={detailArticle}
        collectionName={selectedCollection?.name ?? null}
        onOpenChange={changeDetailOpen}
        onSave={saveFromDetails}
        open={detailArticle !== null}
      />
      <ClearFeedDialog
        clearError={clearFeedMutation.error}
        count={feedSummaryQuery.isError ? null : feedSummaryQuery.data?.articleCount ?? null}
        loadingCount={feedSummaryQuery.isFetching}
        onClose={() => {
          if (!clearFeedMutation.isPending) {
            clearFeedMutation.reset()
            setClearFeedOpen(false)
          }
        }}
        onConfirm={() => void handleClearFeed()}
        onRetryCount={() => void feedSummaryQuery.refetch()}
        open={clearFeedOpen}
        pending={clearFeedMutation.isPending}
      />
      </section>
    </div>
  )
}

function ClearFeedDialog({
  clearError,
  count,
  loadingCount,
  onClose,
  onConfirm,
  onRetryCount,
  open,
  pending,
}: {
  clearError: unknown
  count: number | null
  loadingCount: boolean
  onClose: () => void
  onConfirm: () => void
  onRetryCount: () => void
  open: boolean
  pending: boolean
}) {
  const cancelRef = useRef<HTMLButtonElement | null>(null)
  const titleId = "clear-feed-dialog-title"
  const descriptionId = "clear-feed-dialog-description"
  const errorId = "clear-feed-dialog-error"

  const description = count === null
    ? loadingCount
      ? "Loading the current Feed count…"
      : "The current Feed count is unavailable. Retry the count before clearing."
    : `This will remove ${formatNumber(count)} collected ${count === 1 ? "article" : "articles"} from the Feed.`
  const confirmDisabled = pending || loadingCount || count === null

  return (
    <EditorialDialog
      canClose={!pending}
      className="overflow-y-auto bg-background/45 backdrop-blur-[2px] motion-reduce:transition-none"
      describedBy={`${descriptionId}${clearError ? ` ${errorId}` : ""}`}
      initialFocusRef={cancelRef}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
    >
      <div className="nc-dialog w-full max-w-md space-y-5 p-5">
        <div className="space-y-2">
          <h2 className="text-base font-semibold" id={titleId}>Clear Feed?</h2>
          <div className="space-y-2 text-sm text-muted-foreground" id={descriptionId}>
            <p>{description}</p>
            <p>
              Your Sources, Source Collections, and ingestion settings will remain unchanged. Articles referenced by downstream work will remain available.
            </p>
          </div>
        </div>

        {clearError ? (
          <Alert id={errorId} role="alert" tone="error">
            <div className="flex items-center justify-between gap-3">
              <span>{getApiErrorMessage(clearError, "Feed could not be cleared right now. Try again.")}</span>
              <Button className="shrink-0" disabled={pending} onClick={onConfirm} size="sm" variant="outline">
                Retry clear
              </Button>
            </div>
          </Alert>
        ) : feedSummaryUnavailable(count, loadingCount) ? (
          <Alert role="alert" tone="error">
            <div className="flex items-center justify-between gap-3">
              <span>{description}</span>
              <Button className="shrink-0" disabled={loadingCount} onClick={onRetryCount} size="sm" variant="outline">
                Retry count
              </Button>
            </div>
          </Alert>
        ) : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button disabled={pending} onClick={onClose} ref={cancelRef} type="button" variant="outline">
            Cancel
          </Button>
          <Button
            aria-busy={pending}
            disabled={confirmDisabled}
            onClick={onConfirm}
            type="button"
            variant="destructive"
          >
            {pending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
            {pending ? "Clearing…" : "Clear Feed"}
          </Button>
        </div>
      </div>
    </EditorialDialog>
  )
}

function feedSummaryUnavailable(count: number | null, loadingCount: boolean) {
  return count === null && !loadingCount
}

function ArticleCard({
  article,
  collectionName,
  onSave,
  onViewDetails,
  savePending,
}: {
  article: ArticleSummary
  collectionName: string | null
  onSave: () => void
  onViewDetails: (trigger: HTMLButtonElement) => void
  savePending: boolean
}) {
  const { timezone } = useDateTime()
  const classifications = getArticleCardClassifications(article)
  const time = getArticleCardTime(article.displayAt, article.dateBasis, Date.now(), timezone)
  const originalUrl = safeHttpUrl(article.canonicalUrl)

  return (
    <article className="group relative isolate flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-border/50 bg-card shadow-xs transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-sm">
      <button
        aria-label={`View article details: ${article.title ?? "Untitled article"}`}
        className="absolute inset-0 z-10 cursor-pointer rounded-lg focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        onClick={(event) => onViewDetails(event.currentTarget)}
        type="button"
      />
      <ArticleMedia image={article.image} title={article.title} />
      <div className="flex min-w-0 flex-1 flex-col p-3">
        <DirectionBoundary
          as="h2"
          direction={article.direction}
          language={article.language}
          className="line-clamp-3 min-h-[3.75rem] text-[15px] font-semibold leading-5 text-balance"
        >
          {article.title ?? "Untitled article"}
        </DirectionBoundary>

        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
          <bdi className="max-w-full truncate font-medium text-foreground" dir="auto">{article.source.name ?? "Unknown source"}</bdi>
          <span aria-hidden="true">·</span>
          <time
            aria-label={time.accessibleLabel}
            dateTime={time.dateTime}
            dir="ltr"
            suppressHydrationWarning
            title={time.title}
          >
            {time.relativeLabel}
          </time>
        </div>

        <div className="mt-3 flex min-h-6 flex-wrap items-center gap-1.5">
          <span
            aria-label={`Editorial score: ${article.score}`}
            className="inline-flex items-center gap-1 text-xs tabular-nums text-muted-foreground"
            role="img"
            title={`Editorial score: ${article.score}`}
          >
            <Gauge className="size-3.5" aria-hidden="true" />
            <span aria-hidden="true">{article.score}</span>
          </span>
          {classifications.map((classification) => (
            <Badge
              dir={classification.kind === "language" ? "ltr" : "auto"}
              key={`${classification.kind}:${classification.label}`}
              variant={classification.kind === "content-type" ? "secondary" : "outline"}
            >
              {classification.label}
            </Badge>
          ))}
        </div>

        <footer className="relative z-20 mt-auto flex min-h-8 items-center justify-between gap-2 border-t border-border/50 pt-2.5 text-xs">
          {originalUrl ? (
            <a
              aria-label={`Open original article: ${article.title ?? "Untitled article"}`}
              className="inline-flex min-h-11 cursor-pointer items-center gap-1 rounded-md text-xs font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
              href={originalUrl}
              rel="noreferrer noopener"
              target="_blank"
            >
              Source <ExternalLink className="size-3.5" aria-hidden="true" />
            </a>
          ) : (
            <span className="inline-flex min-h-8 items-center text-muted-foreground">Source unavailable</span>
          )}
          <div className="flex items-center gap-1">
            <Button
              aria-haspopup={collectionName ? undefined : "dialog"}
              aria-label={collectionName ? `Remove article from ${collectionName}` : "Save article to collection"}
              aria-pressed={article.saved}
              className="relative"
              disabled={savePending}
              onClick={onSave}
              size="icon"
              title={collectionName ? `Remove from ${collectionName}` : "Save to Collection"}
              type="button"
              variant={article.saved ? "secondary" : "ghost"}
            >
              {savePending ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Bookmark className="size-4" fill={article.saved ? "currentColor" : "none"} aria-hidden="true" />
              )}
            </Button>
          </div>
        </footer>
      </div>
    </article>
  )
}

function ArticleMedia({ image, title }: { image: ArticleImage | null; title: string | null }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const showImage = image !== null && failedUrl !== image.url
  return (
    <div className="aspect-video w-full shrink-0 overflow-hidden bg-muted">
      {showImage ? (
        <img
          alt={image.altText ?? title ?? ""}
          className="size-full object-cover"
          decoding="async"
          loading="lazy"
          onError={() => setFailedUrl(image.url)}
          src={image.url}
        />
      ) : (
        <div
          aria-label={image ? `Image unavailable for ${title ?? "Untitled article"}` : "No article image"}
          className="flex size-full items-center justify-center bg-muted text-muted-foreground"
          role="img"
        >
          <ImageIcon className="size-7" aria-hidden="true" />
        </div>
      )}
    </div>
  )
}

function ArticleSkeletons() {
  return (
    <div
      role="status"
      aria-label="Loading articles"
      className="feed-card-grid"
    >
      <span className="sr-only">Loading articles</span>
      {Array.from({ length: 8 }, (_, index) => (
        <div
          aria-hidden="true"
          className="flex h-full animate-pulse flex-col overflow-hidden rounded-lg border border-border/50 bg-card motion-reduce:animate-none"
          key={index}
        >
          <div className="aspect-video bg-muted" />
          <div className="flex flex-1 flex-col space-y-3 p-3">
            <div className="h-3 w-2/5 rounded bg-muted" />
            <div className="h-5 w-4/5 rounded bg-muted" />
            <div className="h-3 w-full rounded bg-muted" />
            <div className="mt-auto h-8 w-full rounded bg-muted" />
          </div>
        </div>
      ))}
    </div>
  )
}
