"use client"

import { useQuery } from "@tanstack/react-query"
import { Bookmark, ExternalLink, ImageIcon, X } from "lucide-react"
import { useState } from "react"

import { getArticle } from "./api"
import type { ArticleDetail, ArticleSummary } from "./types"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { SourcePlatform } from "@/features/operations/ingestion-types"
import { formatInTimeZone } from "@/lib/date-time"
import { titleCase } from "@/lib/format"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"

type ArticleDetailDialogProps = {
  article: ArticleSummary | null
  collectionName: string | null
  onOpenChange: (open: boolean) => void
  onSave: (article: ArticleSummary) => void
  open: boolean
}

type EditorialContent = {
  kind: "body" | "excerpt" | "summary" | "unavailable"
  label: string
  text: string | null
}

export function ArticleDetailDialog({
  article,
  collectionName,
  onOpenChange,
  onSave,
  open,
}: ArticleDetailDialogProps) {
  const { timezone } = useDateTime()
  const detailQuery = useQuery({
    queryKey: queryKeys.article(article?.id ?? "closed"),
    queryFn: () => getArticle(article!.id),
    enabled: open && article !== null,
    staleTime: 5 * 60 * 1000,
  })
  const detail = detailQuery.data
  const visibleArticle = detail ?? article
  const originalUrl = safeArticleUrl(visibleArticle?.canonicalUrl)

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        className="flex max-h-[calc(100dvh-1rem)] max-w-4xl flex-col overflow-hidden p-0 sm:max-h-[calc(100dvh-2rem)]"
        viewportClassName="p-2 sm:p-4"
      >
        <DialogClose
          aria-label="Close article details"
          className={cn(buttonVariants({ size: "icon", variant: "secondary" }), "absolute right-3 top-3 z-30 rounded-full shadow-sm")}
        >
          <X aria-hidden="true" />
        </DialogClose>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-testid="article-detail-scroll-region">
          <ArticleDetailHeader article={visibleArticle} />
          <div className="space-y-6 px-4 py-5 sm:px-6">
            <DialogHeader className="sr-only">
              <DialogTitle>{visibleArticle?.title ?? "Untitled article"}</DialogTitle>
              <DialogDescription>
                Article details from {visibleArticle?.source.name ?? "an unknown source"}.
              </DialogDescription>
            </DialogHeader>

            {detailQuery.isPending ? <ArticleDetailSkeleton /> : null}

            {detailQuery.isError ? (
              <Alert role="alert" tone="error">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span dir="auto">
                    {getApiErrorMessage(detailQuery.error, "Article details could not be loaded")}
                  </span>
                  <button
                    className={buttonVariants({ size: "sm", variant: "outline" })}
                    onClick={() => void detailQuery.refetch()}
                    type="button"
                  >
                    Retry
                  </button>
                </div>
              </Alert>
            ) : null}

            {detail ? (
              <>
                <ArticleMetadata detail={detail} timezone={timezone} />
                <ArticleBody detail={detail} />
              </>
            ) : null}
          </div>
        </div>

        <DialogFooter className="shrink-0 bg-card px-4 py-3 sm:px-6">
          <button
            className={buttonVariants({ variant: "outline" })}
            onClick={() => article && onSave(article)}
            type="button"
          >
            <Bookmark aria-hidden="true" fill={article?.saved ? "currentColor" : "none"} />
            {collectionName ? `Remove from ${collectionName}` : "Save to Collection"}
          </button>
          {originalUrl ? (
            <a
              className={buttonVariants()}
              href={originalUrl}
              rel="noopener noreferrer"
              target="_blank"
            >
              Open original source <ExternalLink aria-hidden="true" />
            </a>
          ) : (
            <span className="inline-flex min-h-11 items-center text-sm text-muted-foreground min-[900px]:min-h-8">
              Original source unavailable
            </span>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ArticleDetailHeader({ article }: { article: ArticleSummary | ArticleDetail | null }) {
  if (!article) return null
  return (
    <header className="grid border-b border-border/50 bg-muted/20 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <ArticleHeroMedia article={article} />
      <div className="flex min-w-0 flex-col justify-center px-4 pb-5 pt-4 sm:px-6 md:py-8 md:pr-14">
        <div className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
          <SourceIcon
            className="size-8 shrink-0"
            iconUrl={article.source.iconUrl}
            iconUpdatedAt={article.source.iconUpdatedAt}
            name={article.source.name}
            platform={(article.source.platform ?? "unknown") as SourcePlatform}
            sourceId={article.source.id ?? undefined}
          />
          <bdi className="min-w-0 break-words font-medium text-foreground" dir="auto">
            {article.source.name ?? "Unknown source"}
          </bdi>
        </div>
        <DirectionBoundary
          as="h2"
          className="mt-4 break-words text-balance text-xl font-semibold leading-tight sm:text-2xl"
          direction={article.direction}
          language={article.language}
        >
          {article.title ?? "Untitled article"}
        </DirectionBoundary>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{titleCase(article.contentType)}</Badge>
          {article.topic ? <Badge variant="outline">{article.topic}</Badge> : null}
          {"advanced" in article ? <Badge variant="neutral">{titleCase(article.advanced.status)}</Badge> : null}
          <Badge variant={article.articleReadiness.ready ? "success" : "warning"}>
            {article.articleReadiness.ready ? "Rewrite ready" : "Needs review"}
          </Badge>
        </div>
      </div>
    </header>
  )
}

function ArticleHeroMedia({ article }: { article: ArticleSummary | ArticleDetail }) {
  const image = article.image
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const showImage = image !== null && failedUrl !== image.url
  return (
    <div className="aspect-video min-h-0 w-full overflow-hidden bg-muted md:aspect-auto md:min-h-72">
      {showImage ? (
        <img
          alt={image.altText ?? article.title ?? "Article image"}
          className="size-full object-cover"
          decoding="async"
          onError={() => setFailedUrl(image.url)}
          src={image.url}
        />
      ) : (
        <div
          aria-label={image ? `Image unavailable for ${article.title ?? "Untitled article"}` : "No article image"}
          className="flex size-full min-h-52 items-center justify-center text-muted-foreground"
          role="img"
        >
          <ImageIcon className="size-10" aria-hidden="true" />
        </div>
      )}
    </div>
  )
}

function ArticleMetadata({ detail, timezone }: { detail: ArticleDetail; timezone: string }) {
  const fields = [
    ["Source", detail.source.name ?? "Unknown source"],
    ["Author", detail.authors.length ? detail.authors.join(", ") : "Not provided"],
    ["Published", detail.publishedAt ? formatInTimeZone(detail.publishedAt, timezone) : "Not provided"],
    ["Collected", formatInTimeZone(detail.advanced.createdAt, timezone)],
    ["Content type", titleCase(detail.contentType)],
    ["Rewrite bucket", detail.advanced.rewriteBucket ? titleCase(detail.advanced.rewriteBucket) : "Not assigned"],
    ["Readiness", detail.articleReadiness.ready ? "Ready" : detail.articleReadiness.reason || "Needs review"],
    ["Score", String(detail.score)],
    ["Language", detail.language?.toUpperCase() ?? "Not identified"],
    ["Coverage", titleCase(detail.coverage.state)],
  ]
  return (
    <section aria-labelledby="article-metadata-heading">
      <h3 className="text-sm font-semibold" id="article-metadata-heading">Article metadata</h3>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
        {fields.map(([label, value]) => (
          <div className="min-w-0" key={label}>
            <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
            <dd className="mt-1 break-words text-sm" dir="auto">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function ArticleBody({ detail }: { detail: ArticleDetail }) {
  const content = selectEditorialContent(detail)
  return (
    <section aria-labelledby="article-content-heading" className="border-t border-border/50 pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold" id="article-content-heading">Article content</h3>
        <Badge variant={content.kind === "body" ? "secondary" : "neutral"}>{content.label}</Badge>
      </div>
      {content.text ? (
        <DirectionBoundary
          className="mx-auto mt-4 max-w-[72ch] space-y-4 text-base leading-7 text-foreground [overflow-wrap:anywhere]"
          direction={detail.direction}
          language={detail.language}
        >
          {content.text.replaceAll("\r\n", "\n").split(/\n{2,}/).filter(Boolean).map((paragraph, index) => (
            <p className="whitespace-pre-line break-words" key={index}>{paragraph}</p>
          ))}
        </DirectionBoundary>
      ) : (
        <div className="mt-4 rounded-lg bg-muted/50 px-4 py-5 text-sm text-muted-foreground">
          This source did not provide an article body or excerpt. Open original source when available.
        </div>
      )}
    </section>
  )
}

function ArticleDetailSkeleton() {
  return (
    <div aria-label="Loading article details" className="space-y-5" role="status">
      <span className="sr-only">Loading article details</span>
      <div aria-hidden="true" className="grid animate-pulse grid-cols-2 gap-3 motion-reduce:animate-none sm:grid-cols-4">
        {Array.from({ length: 8 }, (_, index) => <div className="h-12 rounded-md bg-muted" key={index} />)}
      </div>
      <div aria-hidden="true" className="space-y-3 border-t pt-5">
        <div className="h-5 w-40 rounded bg-muted" />
        <div className="h-4 w-full rounded bg-muted" />
        <div className="h-4 w-11/12 rounded bg-muted" />
        <div className="h-4 w-4/5 rounded bg-muted" />
      </div>
    </div>
  )
}

export function selectEditorialContent(detail: ArticleDetail): EditorialContent {
  const contentText = cleanText(detail.contentText)
  if (contentText && detail.contentOrigin !== "unavailable") {
    const labels: Record<ArticleDetail["contentOrigin"], string> = {
      source_provided: "Source-provided content",
      extracted: "Extracted article body",
      source_excerpt: "Source excerpt",
      generated_summary: "Generated summary",
      unavailable: "Content unavailable",
      unknown: "Available article text",
    }
    return {
      kind: detail.contentOrigin === "source_excerpt" || detail.contentOrigin === "generated_summary" ? "excerpt" : "body",
      label: labels[detail.contentOrigin],
      text: contentText,
    }
  }
  const excerpt = cleanText(detail.excerpt)
  if (excerpt) return { kind: "excerpt", label: "Source excerpt", text: excerpt }
  const summary = cleanText(detail.summary)
  if (summary) return { kind: "summary", label: "Source summary", text: summary }
  return { kind: "unavailable", label: "Content unavailable", text: null }
}

export function safeArticleUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null
  } catch {
    return null
  }
}

function cleanText(value: string | null | undefined): string | null {
  const normalized = value?.trim()
  return normalized || null
}
