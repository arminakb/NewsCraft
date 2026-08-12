"use client"

import type { CSSProperties, MouseEvent, ReactNode } from "react"
import { useEffect, useRef, useState } from "react"
import { BookmarkIcon, ExternalLink, X } from "lucide-react"

import { cn } from "@/lib/utils"

export interface NewsCard {
  id: string
  title: string
  category: string
  subcategory: string
  timeAgo: string
  location: string
  image?: string
  imageAlt?: string
  gradientColors?: string[]
  content?: string[]
  sourceUrl?: string
  sourceName?: string
  bookmarked?: boolean
}

export interface StatusBar {
  id: string
  category: string
  subcategory: string
  length: number
  opacity: number
}

export interface NewsCardsProps {
  title?: string
  titleId?: string
  subtitle?: string
  headerAside?: ReactNode
  statusBars?: StatusBar[]
  newsCards?: NewsCard[]
  enableAnimations?: boolean
  isLoading?: boolean
  emptyState?: ReactNode
}

/**
 * Reference implementation adapted from ref/Component.tsx.
 * The card grid keeps its local CSS motion surface; the reference FlipClock
 * is reused directly in flip-clock.tsx with Framer Motion.
 */
export function NewsCards({
  title = "News Today",
  titleId = "news-cards-heading",
  subtitle = "Stories from your monitored sources",
  headerAside,
  statusBars = [],
  newsCards = [],
  enableAnimations = true,
  isLoading = false,
  emptyState,
}: NewsCardsProps) {
  const [isLoaded, setIsLoaded] = useState(!enableAnimations)
  const [selectedCard, setSelectedCard] = useState<NewsCard | null>(null)
  const [closingCard, setClosingCard] = useState<NewsCard | null>(null)
  const [bookmarkedCards, setBookmarkedCards] = useState<Set<string>>(
    () => new Set(newsCards.filter((card) => card.bookmarked).map((card) => card.id)),
  )
  const closeTimerRef = useRef<number | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const lastTriggerRef = useRef<HTMLButtonElement | null>(null)
  const shouldAnimate = enableAnimations && !usePrefersReducedMotion()
  const displayedCard = selectedCard ?? closingCard
  const isClosing = closingCard !== null

  useEffect(() => {
    if (!shouldAnimate) {
      setIsLoaded(true)
      return
    }
    const timer = window.setTimeout(() => setIsLoaded(true), 100)
    return () => window.clearTimeout(timer)
  }, [shouldAnimate])

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    }
  }, [])

  useEffect(() => {
    if (!displayedCard) return
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeCard()
    }
    document.addEventListener("keydown", closeOnEscape)
    return () => document.removeEventListener("keydown", closeOnEscape)
  })

  useEffect(() => {
    if (!selectedCard) return
    const frame = window.requestAnimationFrame(() => closeButtonRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [selectedCard])

  function toggleBookmark(cardId: string, event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    setBookmarkedCards((current) => {
      const next = new Set(current)
      if (next.has(cardId)) next.delete(cardId)
      else next.add(cardId)
      return next
    })
  }

  function openCard(card: NewsCard, trigger?: HTMLButtonElement) {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    lastTriggerRef.current = trigger ?? null
    setClosingCard(null)
    setSelectedCard(card)
  }

  function closeCard() {
    if (!selectedCard || closingCard) return
    setClosingCard(selectedCard)
    setSelectedCard(null)
    closeTimerRef.current = window.setTimeout(() => {
      setClosingCard(null)
      closeTimerRef.current = null
      window.requestAnimationFrame(() => {
        if (lastTriggerRef.current?.isConnected) lastTriggerRef.current.focus()
      })
    }, 180)
  }

  const shellClassName = cn(
    "news-cards-shell mx-auto w-full max-w-6xl p-4 text-foreground sm:p-6",
    shouldAnimate && isLoaded && "news-cards-shell--animate",
  )

  return (
    <div className={shellClassName}>
      <header className="news-cards-header mb-8">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
          <div className="min-w-0">
            <h1 id={titleId} className="mb-2 text-4xl font-bold tracking-tight text-primary">{title}</h1>
            <p className="text-lg text-foreground">{subtitle}</p>
          </div>
          {headerAside ? <div className="shrink-0 self-start sm:pt-1">{headerAside}</div> : null}
        </div>

        <div className="news-cards-status mt-6 space-y-1" aria-label="Today topic activity" role="group">
          {isLoading ? (
            ["w-full", "w-2/3", "w-1/3"].map((width, index) => (
              <div
                className={cn("h-0.5 animate-pulse rounded-full bg-foreground/20", width)}
                key={index}
                aria-hidden="true"
              />
            ))
          ) : (
            statusBars.map((bar, index) => (
              <div
                key={bar.id}
                className={cn(
                  "news-cards-status-bar h-0.5 rounded-full bg-foreground",
                  index === 0 ? "bg-foreground/80" : index === 1 ? "bg-foreground/60" : "bg-foreground/40",
                )}
                style={{
                  opacity: bar.opacity,
                  width: `${Math.max(1, Math.min(3, bar.length)) / 3 * 100}%`,
                  "--news-status-index": index,
                } as CSSProperties}
              >
                <span className="sr-only">{bar.category}: {bar.subcategory}</span>
              </div>
            ))
          )}
        </div>
      </header>

      <div className="news-cards-grid grid grid-cols-1 gap-6 md:grid-cols-2 lg:gap-8 xl:grid-cols-3">
        {isLoading ? (
          <>
            <div role="status" aria-label="Loading Today" className="sr-only">Loading Today</div>
            {Array.from({ length: 3 }, (_, index) => (
              <div
                key={index}
                className="overflow-hidden rounded-lg border border-border/50 bg-card shadow-sm"
                aria-hidden="true"
              >
                <div className="h-56 animate-pulse bg-muted" />
                <div className="space-y-3 p-6">
                  <div className="h-4 w-5/6 animate-pulse rounded bg-muted" />
                  <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
                </div>
              </div>
            ))}
          </>
        ) : newsCards.length ? (
          newsCards.map((card, index) => {
            if (selectedCard?.id === card.id) return null
            const titleHeadingId = `news-card-title-${safeId(card.id)}`
            const bookmarked = bookmarkedCards.has(card.id)

            return (
              <article
                key={card.id}
                className="news-cards-card group relative overflow-hidden rounded-lg border border-border/50 bg-card shadow-sm"
                style={{ "--news-card-index": index } as CSSProperties}
              >
                <button
                  aria-label={`Open story: ${card.title}`}
                  className="absolute inset-0 z-0 cursor-pointer rounded-lg focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  onClick={(event) => openCard(card, event.currentTarget)}
                  type="button"
                />
                <div className="news-cards-card-image pointer-events-none relative z-10 h-56 overflow-hidden bg-muted">
                  {card.image ? (
                    <img
                      src={card.image}
                      alt={card.imageAlt ?? card.title}
                      className="h-full w-full object-cover"
                      decoding="async"
                      loading={index < 3 ? "eager" : "lazy"}
                    />
                  ) : (
                    <div
                      className="flex h-full w-full items-end bg-gradient-to-br from-primary/25 via-muted to-background p-4"
                      role="img"
                      aria-label="No article image available"
                    >
                      <span className="sr-only">No article image available</span>
                    </div>
                  )}
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-background/90 to-transparent" />
                  {card.gradientColors ? (
                    <div className={`pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t ${card.gradientColors[0]} ${card.gradientColors[1]} to-transparent`} />
                  ) : null}

                  <button
                    aria-label={bookmarked ? `Remove bookmark: ${card.title}` : `Bookmark: ${card.title}`}
                    className="pointer-events-auto absolute right-2 top-2 z-10 inline-flex min-h-11 min-w-11 items-center justify-center rounded-full bg-black/20 text-white/80 transition-colors duration-200 hover:bg-black/40 hover:text-white focus-visible:bg-black/50"
                    onClick={(event) => toggleBookmark(card.id, event)}
                    type="button"
                  >
                    <BookmarkIcon className={cn("size-5", bookmarked && "fill-yellow-400 text-yellow-400")} aria-hidden="true" />
                  </button>

                  <div className="pointer-events-none absolute bottom-3 left-3 text-white drop-shadow-sm">
                    <div className="mb-1 text-xs opacity-90">{card.category}, {card.subcategory}</div>
                    <div className="text-xs opacity-80">{card.timeAgo}, {card.location}</div>
                  </div>
                </div>

                <div className="pointer-events-none relative z-10 p-6">
                  <h2 id={titleHeadingId} className="line-clamp-3 text-lg font-semibold leading-tight transition-colors duration-200 group-hover:text-primary">
                    {card.title}
                  </h2>
                </div>
              </article>
            )
          })
        ) : emptyState ? (
          <div className="col-span-full">{emptyState}</div>
        ) : null}
      </div>

      {displayedCard ? (
        <>
          <div
            aria-hidden="true"
            className={cn("news-cards-modal-backdrop fixed inset-0 z-40 cursor-pointer bg-background/80 backdrop-blur-sm", isClosing && "news-cards-modal-backdrop--closing")}
            onClick={closeCard}
          />
          <section
            aria-labelledby={`news-card-dialog-title-${safeId(displayedCard.id)}`}
            aria-modal="true"
            className={cn("news-cards-modal fixed inset-2 z-50 overflow-hidden rounded-xl border border-border bg-card shadow-lg sm:inset-4 md:inset-8 lg:inset-16", isClosing && "news-cards-modal--closing")}
            role="dialog"
          >
            <button
              aria-label="Close story"
              className="absolute right-3 top-3 z-10 inline-flex size-11 items-center justify-center rounded-full bg-background/80 transition-colors duration-200 hover:bg-background focus-visible:bg-background"
              onClick={closeCard}
              ref={closeButtonRef}
              type="button"
            >
              <X className="size-4" aria-hidden="true" />
            </button>

            <div className="h-full overflow-y-auto">
              <div className="relative h-64 bg-muted md:h-80">
                {displayedCard.image ? (
                  <img
                    src={displayedCard.image}
                    alt={displayedCard.imageAlt ?? displayedCard.title}
                    className="h-full w-full object-cover"
                    decoding="async"
                  />
                ) : (
                  <div className="h-full w-full bg-gradient-to-br from-primary/25 via-muted to-background" role="img" aria-label="No article image available" />
                )}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-background/95 to-transparent" />
                {displayedCard.gradientColors ? (
                  <div className={`pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t ${displayedCard.gradientColors[0]} ${displayedCard.gradientColors[1]} to-transparent`} />
                ) : null}
                <div className="absolute bottom-4 left-4 text-white drop-shadow-sm">
                  <div className="mb-1 text-sm opacity-90">{displayedCard.category}, {displayedCard.subcategory}</div>
                  <div className="text-sm opacity-80">{displayedCard.timeAgo}, {displayedCard.location}</div>
                </div>
              </div>

              <div className="space-y-5 p-6 md:p-8">
                <h2 id={`news-card-dialog-title-${safeId(displayedCard.id)}`} className="pr-8 text-2xl font-bold md:text-3xl">
                  {displayedCard.title}
                </h2>
                {displayedCard.sourceUrl ? (
                  <a
                    className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                    href={displayedCard.sourceUrl}
                    rel="noreferrer noopener"
                    target="_blank"
                  >
                    <ExternalLink className="size-4" aria-hidden="true" />
                    Open original{displayedCard.sourceName ? ` at ${displayedCard.sourceName}` : " article"}
                  </a>
                ) : null}

                <div className="space-y-4 text-base leading-7 text-muted-foreground">
                  {displayedCard.content?.length ? (
                    displayedCard.content.map((paragraph, index) => <p key={`${displayedCard.id}-${index}`}>{paragraph}</p>)
                  ) : (
                    <p>
                      Full article text is not available in the Feed summary.
                      {displayedCard.sourceUrl ? " Open the original article for the complete source." : ""}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}

function safeId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]/g, "-")
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false)

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)")
    const handleChange = () => setReduced(mediaQuery.matches)
    handleChange()
    mediaQuery.addEventListener?.("change", handleChange)
    return () => mediaQuery.removeEventListener?.("change", handleChange)
  }, [])

  return reduced
}
