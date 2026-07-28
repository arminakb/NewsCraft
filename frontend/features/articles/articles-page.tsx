"use client"

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bookmark, ExternalLink, Gauge, ImageIcon, LoaderCircle, Search, X } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { ActiveFilterChips, ArticleFilterControl } from "./article-filter-control"
import { getArticleCardClassifications, getArticleCardTime } from "./article-card-metadata"
import { getArticleCollections, getArticleFacets, getArticles, removeArticleFromCollection } from "./api"
import { CollectionsSidebar } from "./collections-sidebar"
import {
  EMPTY_ARTICLE_FILTERS,
  activeFilterCount,
  filtersEqual,
  normalizeArticleSearch,
  readArticleState,
  writeArticleSearch,
  writeArticleState,
} from "./filter-state"
import { SaveToCollectionDialog } from "./save-to-collection-dialog"
import type { ArticleCollection, ArticleImage, ArticleSort, ArticleSummary } from "./types"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/ui/page-header"
import { Select } from "@/components/ui/select"
import { EmptyState, ErrorState } from "@/components/ui/state-panel"
import { formatNumber } from "@/lib/format"
import { ApiError, getApiErrorMessage } from "@/lib/http"

const PAGE_SIZE = 50

export function ArticlesPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const search = searchParams.toString()
  const { sort, filters, query: titleQuery } = useMemo(() => readArticleState(new URLSearchParams(search)), [search])
  const collectionId = useMemo(() => new URLSearchParams(search).get("collection_id"), [search])
  const filterCount = activeFilterCount(filters)
  const [announcement, setAnnouncement] = useState("")
  const [savingArticle, setSavingArticle] = useState<ArticleSummary | null>(null)
  const [membershipPending, setMembershipPending] = useState(false)
  const [directRemovalPendingId, setDirectRemovalPendingId] = useState<string | null>(null)
  const [directRemovalError, setDirectRemovalError] = useState<{ article: ArticleSummary; message: string } | null>(null)
  const [focusAllFeedToken, setFocusAllFeedToken] = useState(0)
  const [searchInput, setSearchInput] = useState({ value: titleQuery, committedQuery: titleQuery })
  const searchDraft = searchInput.committedQuery === titleQuery ? searchInput.value : titleQuery
  const directRemovalBusyRef = useRef(false)
  const searchTimerRef = useRef<number | null>(null)
  const searchSyncFrameRef = useRef<number | null>(null)
  const collectionsQuery = useQuery({
    queryKey: ["article-collections"],
    queryFn: getArticleCollections,
  })
  const selectedCollection = collectionsQuery.data?.find((collection) => collection.id === collectionId)
  const missingFromList = Boolean(collectionId && collectionsQuery.isSuccess && !selectedCollection)
  const facetsQuery = useQuery({
    queryKey: ["articles", "facets"],
    queryFn: getArticleFacets,
    staleTime: Infinity,
  })
  const query = useInfiniteQuery({
    queryKey: ["articles", "list", sort, filters, titleQuery, selectedCollection?.id ?? null],
    queryFn: ({ pageParam }) => getArticles({
      sort,
      ...(titleQuery ? { query: titleQuery } : {}),
      filters,
      ...(selectedCollection ? { collectionId: selectedCollection.id } : {}),
      cursor: pageParam,
      limit: PAGE_SIZE,
    }),
    enabled: collectionId === null || Boolean(selectedCollection),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
  })
  const articles = useMemo(() => {
    const seen = new Set<string>()
    return (query.data?.pages ?? []).flatMap((page) => page.items).filter((article) => {
      if (seen.has(article.id)) return false
      seen.add(article.id)
      return true
    })
  }, [query.data?.pages])
  const resultCount = query.data?.pages.at(-1)?.resultCount
  const collectionDeleted = Boolean(collectionId && query.error instanceof ApiError && query.error.status === 404)
  const unavailableSelection = missingFromList || collectionDeleted

  useEffect(() => setSearchInput({ value: titleQuery, committedQuery: titleQuery }), [titleQuery])

  useEffect(() => {
    const syncSearchFromLocation = () => {
      if (searchTimerRef.current !== null) {
        window.clearTimeout(searchTimerRef.current)
        searchTimerRef.current = null
      }
      if (searchSyncFrameRef.current !== null) window.cancelAnimationFrame(searchSyncFrameRef.current)
      searchSyncFrameRef.current = window.requestAnimationFrame(() => {
        const params = new URLSearchParams(window.location.search)
        const queryFromUrl = normalizeArticleSearch(params.get("q") ?? "")
        setSearchInput({ value: queryFromUrl, committedQuery: queryFromUrl })
        searchSyncFrameRef.current = null
      })
    }
    window.addEventListener("popstate", syncSearchFromLocation)
    window.addEventListener("pageshow", syncSearchFromLocation)
    return () => {
      window.removeEventListener("popstate", syncSearchFromLocation)
      window.removeEventListener("pageshow", syncSearchFromLocation)
      if (searchSyncFrameRef.current !== null) window.cancelAnimationFrame(searchSyncFrameRef.current)
    }
  }, [])

  useEffect(() => {
    const normalized = normalizeArticleSearch(searchDraft)
    if (normalized === titleQuery) return
    const timer = window.setTimeout(() => {
      searchTimerRef.current = null
      const liveParams = new URLSearchParams(window.location.search)
      if (normalizeArticleSearch(liveParams.get("q") ?? "") === normalized) return
      const params = writeArticleSearch(liveParams, normalized)
      const queryString = params.toString()
      window.history.pushState(null, "", `${pathname}${queryString ? `?${queryString}` : ""}`)
    }, 300)
    searchTimerRef.current = timer
    return () => {
      window.clearTimeout(timer)
      if (searchTimerRef.current === timer) searchTimerRef.current = null
    }
  }, [pathname, search, searchDraft, titleQuery])

  const changeSearchDraft = (value: string) => setSearchInput({ value, committedQuery: titleQuery })

  const navigate = useCallback((nextSort: ArticleSort, nextFilters: typeof filters) => {
    const params = writeArticleState(new URLSearchParams(search), nextSort, nextFilters)
    const queryString = params.toString()
    router.push(`${pathname}${queryString ? `?${queryString}` : ""}`, { scroll: false })
  }, [pathname, router, search])
  const changeFilters = (nextFilters: typeof filters) => {
    if (!filtersEqual(filters, nextFilters)) navigate(sort, nextFilters)
  }

  const selectCollection = useCallback((nextCollectionId: string | null) => {
    const params = new URLSearchParams(search)
    params.delete("cursor")
    if (nextCollectionId) params.set("collection_id", nextCollectionId)
    else params.delete("collection_id")
    const queryString = params.toString()
    router.push(`${pathname}${queryString ? `?${queryString}` : ""}`, { scroll: false })
  }, [pathname, router, search])

  const handleCollectionCreated = useCallback((collection: ArticleCollection) => {
    queryClient.setQueryData<ArticleCollection[]>(["article-collections"], (current = []) => (
      [...current.filter((item) => item.id !== collection.id), collection]
        .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }))
    ))
    void queryClient.invalidateQueries({ queryKey: ["article-collections"] })
    setAnnouncement(`Collection ${collection.name} created and selected.`)
    selectCollection(collection.id)
  }, [queryClient, selectCollection])

  const handleInlineCollectionCreated = useCallback((collection: ArticleCollection) => {
    queryClient.setQueryData<ArticleCollection[]>(["article-collections"], (current = []) => (
      [...current.filter((item) => item.id !== collection.id), collection]
        .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }))
    ))
    void queryClient.invalidateQueries({ queryKey: ["article-collections"] })
    setAnnouncement(`Collection ${collection.name} created and selected in the Save dialog.`)
  }, [queryClient])

  const reconcileMemberships = useCallback(async (articleId: string, confirmedCollectionIds: string[]) => {
    const [articlesResult] = await Promise.all([
      query.refetch({ throwOnError: true }),
      collectionsQuery.refetch({ throwOnError: true }),
    ])
    const refreshedArticle = articlesResult.data?.pages
      .flatMap((page) => page.items)
      .find((article) => article.id === articleId)
    return refreshedArticle?.savedCollectionIds ?? confirmedCollectionIds
  }, [collectionsQuery, query])

  const handleCollectionRenamed = useCallback(async (collection: ArticleCollection) => {
    queryClient.setQueryData<ArticleCollection[]>(["article-collections"], (current = []) => (
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
        message: getApiErrorMessage(cause, "Article was removed, but the Library could not be refreshed. Retry to reconcile."),
      })
    } finally {
      directRemovalBusyRef.current = false
      setDirectRemovalPendingId(null)
    }
  }, [collectionsQuery, query, selectedCollection])

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
        title="Library"
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
        </div>}
      />

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

      {!unavailableSelection && query.isPending ? <ArticleSkeletons /> : null}

      {!unavailableSelection && query.isError && articles.length === 0 ? (
        <ErrorState
          title="Library unavailable"
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
                ? "Use Save to Collection on a Library card to add articles here."
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
            Showing {formatNumber(articles.length)} of {formatNumber(resultCount ?? articles.length)}
          </p>
          <div
            className="feed-card-grid"
            aria-label="Library results"
          >
            {articles.map((article) => (
              <ArticleCard
                article={article}
                key={article.id}
                collectionName={selectedCollection?.name ?? null}
                onSave={() => selectedCollection
                  ? void handleDirectRemoval(article)
                  : setSavingArticle(article)}
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
              {getApiErrorMessage(query.error, "More articles could not be loaded")}
            </Alert>
          ) : null}

          {query.hasNextPage ? (
            <div className="flex justify-center pb-20 pt-1">
              <Button
                className="min-w-36 scroll-mb-4"
                disabled={query.isFetchingNextPage}
                variant="outline"
                onFocus={(event) => {
                  const scrollContainer = event.currentTarget.closest<HTMLElement>(".newsroom-scroll")
                  if (!scrollContainer) return
                  const buttonBounds = event.currentTarget.getBoundingClientRect()
                  const scrollBounds = scrollContainer.getBoundingClientRect()
                  if (buttonBounds.bottom > scrollBounds.bottom) {
                    scrollContainer.scrollTop += buttonBounds.bottom - scrollBounds.bottom + 16
                  }
                }}
                onClick={() => query.fetchNextPage()}
              >
                {query.isFetchingNextPage ? "Loading more…" : "Load more"}
              </Button>
            </div>
          ) : (
            <p className="text-center text-xs text-muted-foreground">All loaded</p>
          )}
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
      </section>
    </div>
  )
}

function ArticleCard({
  article,
  collectionName,
  onSave,
  savePending,
}: {
  article: ArticleSummary
  collectionName: string | null
  onSave: () => void
  savePending: boolean
}) {
  const classifications = getArticleCardClassifications(article)
  const time = getArticleCardTime(article.displayAt, article.dateBasis)

  return (
    <article className="group flex h-full min-w-0 flex-col overflow-hidden rounded-lg border border-border/50 bg-card shadow-xs transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-sm">
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

        <footer className="mt-auto flex min-h-8 items-center justify-between gap-2 border-t border-border/50 pt-2.5 text-xs">
          {article.canonicalUrl ? (
            <a
              aria-label={`Open original article: ${article.title ?? "Untitled article"}`}
              className="inline-flex min-h-11 cursor-pointer items-center gap-1 rounded-md text-xs font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
              href={article.canonicalUrl}
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
