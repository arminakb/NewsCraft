"use client"

import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useState, type ReactNode } from "react"

import {
  getLibraryDrafts,
  getLibraryEvidence,
  getLibraryExports,
  getLibraryOriginals,
  getLibraryPublications,
  getLibraryResearchRuns,
  getLibraryStories,
  type LibraryDraft,
  type LibraryEvidence,
  type LibraryExport,
  type LibraryOriginal,
  type LibraryPublication,
  type LibraryResearchRun,
  type LibraryStory,
} from "./api"
import { getApiErrorMessage } from "@/lib/http"

const tabs = [
  { id: "originals", label: "Originals" },
  { id: "stories", label: "Stories" },
  { id: "evidence", label: "Evidence" },
  { id: "research", label: "Research" },
  { id: "drafts", label: "Drafts" },
  { id: "exports", label: "Exports" },
  { id: "publications", label: "Publications" },
] as const

type TabId = (typeof tabs)[number]["id"]

export function LibraryPage() {
  const [activeTab, setActiveTab] = useState<TabId>("originals")

  const originalsQuery = useInfiniteQuery({
    queryKey: ["library", "originals"],
    queryFn: ({ pageParam }) => getLibraryOriginals(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: activeTab === "originals",
  })
  const storiesQuery = useInfiniteQuery({
    queryKey: ["library", "stories"],
    queryFn: ({ pageParam }) => getLibraryStories(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: activeTab === "stories",
  })
  const evidenceQuery = useInfiniteQuery({
    queryKey: ["library", "evidence"],
    queryFn: ({ pageParam }) => getLibraryEvidence(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: activeTab === "evidence",
  })
  const researchQuery = useInfiniteQuery({
    queryKey: ["library", "research"],
    queryFn: ({ pageParam }) => getLibraryResearchRuns(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: activeTab === "research",
  })
  const draftsQuery = useQuery({
    queryKey: ["library", "drafts"],
    queryFn: getLibraryDrafts,
    enabled: activeTab === "drafts",
  })
  const exportsQuery = useInfiniteQuery({
    queryKey: ["library", "exports"],
    queryFn: ({ pageParam }) => getLibraryExports(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: activeTab === "exports",
  })
  const publicationsQuery = useInfiniteQuery({
    queryKey: ["library", "publications"],
    queryFn: ({ pageParam }) => getLibraryPublications(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: activeTab === "publications",
  })

  const originals = originalsQuery.data?.pages.flatMap((page) => page.items) ?? []
  const stories = storiesQuery.data?.pages.flatMap((page) => page.items) ?? []
  const evidence = evidenceQuery.data?.pages.flatMap((page) => page.items) ?? []
  const researchRuns = researchQuery.data?.pages.flatMap((page) => page.items) ?? []
  const exports = exportsQuery.data?.pages.flatMap((page) => page.items) ?? []
  const publications = publicationsQuery.data?.pages.flatMap((page) => page.items) ?? []
  const active = tabs.find((tab) => tab.id === activeTab) ?? tabs[0]

  return (
    <main className="space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold">Library</h1>
        <p className="text-muted-foreground">
          Read-only views of persisted originals, editorial records, artifacts, and publications.
        </p>
      </header>

      <div aria-label="Library sections" className="flex flex-wrap gap-2" role="tablist">
        {tabs.map((tab) => (
          <button
            aria-controls={`library-panel-${tab.id}`}
            aria-selected={activeTab === tab.id}
            className="rounded-md border px-3 py-2 text-sm aria-selected:bg-primary aria-selected:text-primary-foreground"
            id={`library-tab-${tab.id}`}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <section
        aria-label={active.label}
        aria-labelledby={`library-tab-${active.id}`}
        id={`library-panel-${active.id}`}
        role="tabpanel"
      >
        {activeTab === "originals" ? (
          <PanelState
            emptyMessage="No originals found."
            error={originalsQuery.error}
            errorFallback="Originals could not be loaded"
            isEmpty={originalsQuery.isSuccess && originals.length === 0}
            isPending={originalsQuery.isPending}
            loadingLabel="Loading originals"
          >
            <OriginalList items={originals} />
            <ContinuationButton
              fetchNext={() => originalsQuery.fetchNextPage()}
              hasNext={originalsQuery.hasNextPage}
              loading={originalsQuery.isFetchingNextPage}
              noun="originals"
            />
          </PanelState>
        ) : null}

        {activeTab === "stories" ? (
          <PanelState
            emptyMessage="No stories found."
            error={storiesQuery.error}
            errorFallback="Stories could not be loaded"
            isEmpty={storiesQuery.isSuccess && stories.length === 0}
            isPending={storiesQuery.isPending}
            loadingLabel="Loading stories"
          >
            <StoryList items={stories} />
            <ContinuationButton
              fetchNext={() => storiesQuery.fetchNextPage()}
              hasNext={storiesQuery.hasNextPage}
              loading={storiesQuery.isFetchingNextPage}
              noun="stories"
            />
          </PanelState>
        ) : null}

        {activeTab === "evidence" ? (
          <PanelState
            emptyMessage="No evidence snapshots found."
            error={evidenceQuery.error}
            errorFallback="Evidence snapshots could not be loaded"
            isEmpty={evidenceQuery.isSuccess && evidence.length === 0}
            isPending={evidenceQuery.isPending}
            loadingLabel="Loading evidence"
          >
            <EvidenceList items={evidence} />
            <ContinuationButton
              fetchNext={() => evidenceQuery.fetchNextPage()}
              hasNext={evidenceQuery.hasNextPage}
              loading={evidenceQuery.isFetchingNextPage}
              noun="evidence"
            />
          </PanelState>
        ) : null}

        {activeTab === "research" ? (
          <PanelState
            emptyMessage="No research runs found."
            error={researchQuery.error}
            errorFallback="Research runs could not be loaded"
            isEmpty={researchQuery.isSuccess && researchRuns.length === 0}
            isPending={researchQuery.isPending}
            loadingLabel="Loading research"
          >
            <ResearchList items={researchRuns} />
            <ContinuationButton
              fetchNext={() => researchQuery.fetchNextPage()}
              hasNext={researchQuery.hasNextPage}
              loading={researchQuery.isFetchingNextPage}
              noun="research"
            />
          </PanelState>
        ) : null}

        {activeTab === "drafts" ? (
          <PanelState
            emptyMessage="No current draft revisions found."
            error={draftsQuery.error}
            errorFallback="Draft revisions could not be loaded"
            isEmpty={draftsQuery.isSuccess && draftsQuery.data.length === 0}
            isPending={draftsQuery.isPending}
            loadingLabel="Loading drafts"
          >
            <DraftList items={draftsQuery.data ?? []} />
          </PanelState>
        ) : null}

        {activeTab === "exports" ? (
          <PanelState
            emptyMessage="No finished exports found."
            error={exportsQuery.error}
            errorFallback="Exports could not be loaded"
            isEmpty={exportsQuery.isSuccess && exports.length === 0}
            isPending={exportsQuery.isPending}
            loadingLabel="Loading exports"
          >
            <ExportList items={exports} />
            <ContinuationButton
              fetchNext={() => exportsQuery.fetchNextPage()}
              hasNext={exportsQuery.hasNextPage}
              loading={exportsQuery.isFetchingNextPage}
              noun="exports"
            />
          </PanelState>
        ) : null}

        {activeTab === "publications" ? (
          <PanelState
            emptyMessage="No publications found."
            error={publicationsQuery.error}
            errorFallback="Publications could not be loaded"
            isEmpty={publicationsQuery.isSuccess && publications.length === 0}
            isPending={publicationsQuery.isPending}
            loadingLabel="Loading publications"
          >
            <PublicationList items={publications} />
            <ContinuationButton
              fetchNext={() => publicationsQuery.fetchNextPage()}
              hasNext={publicationsQuery.hasNextPage}
              loading={publicationsQuery.isFetchingNextPage}
              noun="publications"
            />
          </PanelState>
        ) : null}
      </section>
    </main>
  )
}

function PanelState({
  children,
  emptyMessage,
  error,
  errorFallback,
  isEmpty,
  isPending,
  loadingLabel,
}: {
  children: ReactNode
  emptyMessage: string
  error: unknown
  errorFallback: string
  isEmpty: boolean
  isPending: boolean
  loadingLabel: string
}) {
  if (isPending) {
    return <div aria-label={loadingLabel} role="status">{loadingLabel}…</div>
  }
  if (error && isEmpty) {
    return <div className="text-red-700" role="alert">{getApiErrorMessage(error, errorFallback)}</div>
  }
  if (isEmpty) return <p>{emptyMessage}</p>
  return (
    <div className="space-y-4">
      {error ? <div className="text-red-700" role="alert">{getApiErrorMessage(error, errorFallback)}</div> : null}
      {children}
    </div>
  )
}

function OriginalList({ items }: { items: LibraryOriginal[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={item.id}>
      <RecordHeading title={item.title || "Untitled original"} status={item.status} />
      <p className="text-sm text-muted-foreground">{item.sourceName ?? "Source not recorded"} · {displayTime(item.publishedAt)}</p>
      {safeExternalUrl(item.sourceUrl) ? (
        <a className="text-primary underline" href={item.sourceUrl as string} rel="noreferrer" target="_blank">Open original source</a>
      ) : <p className="text-sm text-muted-foreground">Original source URL unavailable.</p>}
    </li>
  ))}</RecordList>
}

function StoryList({ items }: { items: LibraryStory[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={item.id}>
      <RecordHeading title={item.title} status={item.status} />
      <p className="text-sm text-muted-foreground">{item.evidenceCount} evidence snapshots · updated {displayTime(item.updatedAt)}</p>
      <Link className="text-primary underline" href={`/inbox?story_id=${encodeURIComponent(item.id)}`}>Open story</Link>
    </li>
  ))}</RecordList>
}

function EvidenceList({ items }: { items: LibraryEvidence[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={item.id}>
      <RecordHeading title={item.title ?? "Untitled evidence"} status="snapshot" />
      <p className="text-sm leading-6">{item.excerpt}</p>
      <p className="text-xs text-muted-foreground">Captured {displayTime(item.capturedAt)} · SHA-256 {item.contentSha256}</p>
      <Link className="text-primary underline" href={`/inbox?story_id=${encodeURIComponent(item.storyId)}&evidence_id=${encodeURIComponent(item.id)}`}>Open evidence snapshot</Link>
    </li>
  ))}</RecordList>
}

function ResearchList({ items }: { items: LibraryResearchRun[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={item.id}>
      <RecordHeading title={`${item.requestedMode.replaceAll("_", " ")} research`} status={item.status} />
      <p className="text-sm text-muted-foreground">
        {item.backend ?? "No backend"} · {item.attemptCount} attempts · {item.sourceCount} sources · {item.budget.maxQueries}/{item.budget.maxPages}/{item.budget.maxElapsedSeconds}s budget
      </p>
      {item.errorSummary ? <p className="text-sm text-red-700">{item.errorSummary}</p> : null}
      <div className="flex flex-wrap gap-3">
        <Link className="text-primary underline" href={`/inbox?story_id=${encodeURIComponent(item.storyId)}&research_run_id=${encodeURIComponent(item.id)}`}>Open research run</Link>
        {item.resultRevisionId ? <span className="text-sm text-muted-foreground">Story revision {item.resultRevisionId}</span> : null}
      </div>
    </li>
  ))}</RecordList>
}

function DraftList({ items }: { items: LibraryDraft[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={item.revisionId}>
      <RecordHeading title={`${item.platform.toUpperCase()} revision ${item.revisionNumber}`} status={item.approvalState} />
      <p className="text-sm text-muted-foreground">Pack {item.packId} · updated {displayTime(item.updatedAt)}</p>
      <Link className="text-primary underline" href={`/review/${encodeURIComponent(item.revisionId)}`}>Open exact revision</Link>
    </li>
  ))}</RecordList>
}

function ExportList({ items }: { items: LibraryExport[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={item.id}>
      <RecordHeading title={`Export ${item.id}`} status={item.status} />
      <p className="text-sm text-muted-foreground">Pack {item.contentPackId ?? "unavailable"} · finished {displayTime(item.finishedAt)}</p>
      {item.errorSummary ? <p className="text-sm text-red-700">{item.errorSummary}</p> : null}
      <div className="flex flex-wrap gap-3">
        <a className="text-primary underline" href={backendPath(`/exports/${item.id}`)}>Open exact export</a>
        {safeDownloadPath(item.downloads[0], item.id) ? <a className="text-primary underline" href={backendPath(item.downloads[0])}>Download export</a> : null}
      </div>
    </li>
  ))}</RecordList>
}

function PublicationList({ items }: { items: LibraryPublication[] }) {
  return <RecordList>{items.map((item) => (
    <li className="rounded-lg border p-4" key={`${item.kind}:${item.id}`}>
      <RecordHeading title={`${item.platform.toUpperCase()} publication`} status={item.status} />
      <p className="text-sm text-muted-foreground">Published {displayTime(item.occurredAt)}</p>
      <div className="flex flex-wrap gap-3">
        {safeExternalUrl(item.externalUrl) ? <a className="text-primary underline" href={item.externalUrl as string} rel="noreferrer" target="_blank">Open exact publication</a> : <span className="text-sm text-muted-foreground">Publication URL unavailable.</span>}
        {safeReviewPath(item.actionUrl, item.revisionId) ? <Link className="text-primary underline" href={item.actionUrl}>Review published revision</Link> : <span className="text-sm text-muted-foreground">Review link unavailable.</span>}
      </div>
    </li>
  ))}</RecordList>
}

function RecordList({ children }: { children: ReactNode }) {
  return <ul className="grid gap-3">{children}</ul>
}

function RecordHeading({ status, title }: { status: string; title: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <h2 className="font-medium">{title}</h2>
      <span className="rounded border px-2 py-0.5 text-xs capitalize">{status.replaceAll("_", " ")}</span>
    </div>
  )
}

function ContinuationButton({
  fetchNext,
  hasNext,
  loading,
  noun,
}: {
  fetchNext: () => Promise<unknown>
  hasNext: boolean
  loading: boolean
  noun: string
}) {
  if (!hasNext) return null
  return (
    <button
      className="rounded-md border px-3 py-2 text-sm"
      disabled={loading}
      onClick={() => void fetchNext()}
      type="button"
    >
      {loading ? `Loading more ${noun}…` : `Load more ${noun}`}
    </button>
  )
}

function displayTime(value: string | null): string {
  if (!value) return "not recorded"
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function safeExternalUrl(value: string | null): boolean {
  if (!value) return false
  try {
    const parsed = new URL(value)
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && !parsed.username && !parsed.password
  } catch {
    return false
  }
}

function backendPath(path: string): string {
  return path.startsWith("/api/backend/") ? path : `/api/backend${path.startsWith("/") ? path : `/${path}`}`
}

function safeReviewPath(path: string, revisionId: string): boolean {
  return path === `/review/${revisionId}`
}

function safeDownloadPath(path: string | undefined, exportId: string): boolean {
  if (!path) return false
  const prefix = `/exports/${exportId}/download/`
  if (!path.startsWith(prefix) || path.includes("\\") || path.includes("?") || path.includes("#")) return false
  try {
    const relative = decodeURIComponent(path.slice(prefix.length))
    return Boolean(relative) && relative.split("/").every((part) => Boolean(part) && part !== "." && part !== "..")
  } catch {
    return false
  }
}
