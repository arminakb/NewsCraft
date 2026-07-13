import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import {
  getLibraryDrafts,
  getLibraryEvidence,
  getLibraryExports,
  getLibraryOriginals,
  getLibraryPublications,
  getLibraryResearchRuns,
  getLibraryStories,
} from "@/features/library/api"
import { LibraryPage } from "@/features/library/library-page"

vi.mock("@/features/library/api", () => ({
  getLibraryDrafts: vi.fn(),
  getLibraryEvidence: vi.fn(),
  getLibraryExports: vi.fn(),
  getLibraryOriginals: vi.fn(),
  getLibraryPublications: vi.fn(),
  getLibraryResearchRuns: vi.fn(),
  getLibraryStories: vi.fn(),
}))

const emptyPage = { items: [], nextCursor: null }

describe("LibraryPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getLibraryOriginals).mockResolvedValue(emptyPage)
    vi.mocked(getLibraryStories).mockResolvedValue(emptyPage)
    vi.mocked(getLibraryEvidence).mockResolvedValue(emptyPage)
    vi.mocked(getLibraryResearchRuns).mockResolvedValue(emptyPage)
    vi.mocked(getLibraryDrafts).mockResolvedValue([])
    vi.mocked(getLibraryExports).mockResolvedValue(emptyPage)
    vi.mocked(getLibraryPublications).mockResolvedValue(emptyPage)
  })

  it("renders exactly seven truthful tabs and gives every tab its own panel", async () => {
    renderLibrary()

    const expected = [
      "Originals",
      "Stories",
      "Evidence",
      "Research",
      "Drafts",
      "Exports",
      "Publications",
    ]
    expect(screen.getAllByRole("tab")).toHaveLength(7)
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(expected)

    for (const label of expected) {
      fireEvent.click(screen.getByRole("tab", { name: label }))
      expect(screen.getByRole("tabpanel", { name: label })).toBeInTheDocument()
    }
  })

  it("does not let one tab's loading or error state replace another tab's truth", async () => {
    vi.mocked(getLibraryOriginals).mockReturnValue(new Promise(() => undefined))
    vi.mocked(getLibraryStories).mockResolvedValue({
      items: [{
        id: "story-1",
        title: "Persisted story",
        status: "shortlisted",
        evidenceCount: 2,
        updatedAt: "2026-07-13T08:00:00Z",
      }],
      nextCursor: null,
    })
    vi.mocked(getLibraryEvidence).mockRejectedValue(new Error("evidence database unavailable"))
    renderLibrary()

    expect(screen.getByRole("status", { name: "Loading originals" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: "Stories" }))
    expect(await screen.findByText("Persisted story")).toBeInTheDocument()
    expect(screen.queryByRole("status", { name: "Loading originals" })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("evidence database unavailable")

    fireEvent.click(screen.getByRole("tab", { name: "Stories" }))
    expect(screen.getByText("Persisted story")).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: "Originals" }))
    expect(screen.getByRole("status", { name: "Loading originals" })).toBeInTheDocument()
  })

  it("shows distinct empty states instead of reusing another tab's records", async () => {
    renderLibrary()

    expect(await screen.findByText("No originals found.")).toBeInTheDocument()
    const cases = [
      ["Stories", "No stories found."],
      ["Evidence", "No evidence snapshots found."],
      ["Research", "No research runs found."],
      ["Drafts", "No current draft revisions found."],
      ["Exports", "No finished exports found."],
      ["Publications", "No publications found."],
    ] as const

    for (const [tab, message] of cases) {
      fireEvent.click(screen.getByRole("tab", { name: tab }))
      expect(await screen.findByText(message)).toBeInTheDocument()
    }
  })

  it("deep-links each record to its persisted source, story, snapshot, run, revision, export, or publication", async () => {
    vi.mocked(getLibraryOriginals).mockResolvedValue({ items: [{
      id: "content-1",
      title: "Original report",
      status: "approved",
      sourceId: "source-1",
      sourceName: "Wire Desk",
      sourceUrl: "https://source.example/report",
      publishedAt: "2026-07-13T07:00:00Z",
      sortAt: "2026-07-13T07:00:00Z",
    }], nextCursor: null })
    vi.mocked(getLibraryStories).mockResolvedValue({ items: [{
      id: "story-1", title: "Story", status: "inbox", evidenceCount: 1,
      updatedAt: "2026-07-13T08:00:00Z",
    }], nextCursor: null })
    vi.mocked(getLibraryEvidence).mockResolvedValue({ items: [{
      id: "evidence-1", storyId: "story-1", contentItemId: "content-1",
      evidenceKey: "url:key", title: "Evidence", sourceUrl: "https://source.example/report",
      authors: ["Reporter"], publishedAt: null, capturedAt: "2026-07-13T08:00:00Z",
      contentSha256: "a".repeat(64), excerpt: "Bounded evidence",
    }], nextCursor: null })
    vi.mocked(getLibraryResearchRuns).mockResolvedValue({ items: [{
      id: "run-1", storyId: "story-1", requestedMode: "manual", backend: "openrouter",
      status: "succeeded", budget: { maxQueries: 4, maxPages: 8, maxElapsedSeconds: 120 },
      createdAt: "2026-07-13T08:00:00Z", startedAt: null, finishedAt: null,
      attemptCount: 1, sourceCount: 3, resultRevisionId: "story-revision-1", errorSummary: null,
    }], nextCursor: null })
    vi.mocked(getLibraryDrafts).mockResolvedValue([{
      packId: "pack-1", storyId: "story-1", platform: "x", revisionId: "revision-1",
      revisionNumber: 2, approvalState: "pending_review", updatedAt: "2026-07-13T08:00:00Z",
    }])
    vi.mocked(getLibraryExports).mockResolvedValue({ items: [{
      id: "export-1", status: "succeeded", finishedAt: "2026-07-13T08:00:00Z",
      contentPackId: "pack-1", downloads: ["/exports/export-1/download/bundle.zip"], errorSummary: null,
    }], nextCursor: null })
    vi.mocked(getLibraryPublications).mockResolvedValue({ items: [{
      id: "publication-1", kind: "manual_publication", platform: "x", revisionId: "revision-1",
      occurredAt: "2026-07-13T08:00:00Z", status: "manual_published",
      externalUrl: "https://x.example/post/1", actionUrl: "/review/revision-1",
    }], nextCursor: null })
    renderLibrary()

    expect(await screen.findByRole("link", { name: "Open original source" })).toHaveAttribute(
      "href",
      "https://source.example/report",
    )

    fireEvent.click(screen.getByRole("tab", { name: "Stories" }))
    expect(await screen.findByRole("link", { name: "Open story" })).toHaveAttribute(
      "href",
      "/inbox?story_id=story-1",
    )

    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }))
    expect(await screen.findByRole("link", { name: "Open evidence snapshot" })).toHaveAttribute(
      "href",
      "/inbox?story_id=story-1&evidence_id=evidence-1",
    )

    fireEvent.click(screen.getByRole("tab", { name: "Research" }))
    expect(await screen.findByRole("link", { name: "Open research run" })).toHaveAttribute(
      "href",
      "/inbox?story_id=story-1&research_run_id=run-1",
    )

    fireEvent.click(screen.getByRole("tab", { name: "Drafts" }))
    expect(await screen.findByRole("link", { name: "Open exact revision" })).toHaveAttribute(
      "href",
      "/review/revision-1",
    )

    fireEvent.click(screen.getByRole("tab", { name: "Exports" }))
    expect(await screen.findByRole("link", { name: "Open exact export" })).toHaveAttribute(
      "href",
      "/api/backend/exports/export-1",
    )
    expect(screen.getByRole("link", { name: "Download export" })).toHaveAttribute(
      "href",
      "/api/backend/exports/export-1/download/bundle.zip",
    )

    fireEvent.click(screen.getByRole("tab", { name: "Publications" }))
    expect(await screen.findByRole("link", { name: "Open exact publication" })).toHaveAttribute(
      "href",
      "https://x.example/post/1",
    )
    expect(screen.getByRole("link", { name: "Review published revision" })).toHaveAttribute(
      "href",
      "/review/revision-1",
    )
  })

  it("only requests a tab when the operator opens it", async () => {
    renderLibrary()
    await waitFor(() => expect(getLibraryOriginals).toHaveBeenCalledTimes(1))
    expect(getLibraryStories).not.toHaveBeenCalled()
    expect(getLibraryEvidence).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole("tab", { name: "Research" }))
    await waitFor(() => expect(getLibraryResearchRuns).toHaveBeenCalledTimes(1))
    expect(getLibraryEvidence).not.toHaveBeenCalled()
    expect(getLibraryDrafts).not.toHaveBeenCalled()
  })

  it("uses the persisted continuation cursor without replacing earlier records", async () => {
    vi.mocked(getLibraryEvidence)
      .mockResolvedValueOnce({
        items: [evidence("evidence-1")],
        nextCursor: "cursor-2",
      })
      .mockResolvedValueOnce({
        items: [evidence("evidence-2")],
        nextCursor: null,
      })
    renderLibrary()

    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }))
    expect(await screen.findByText("Evidence evidence-1")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Load more evidence" }))

    await waitFor(() => expect(getLibraryEvidence).toHaveBeenLastCalledWith("cursor-2"))
    expect(screen.getByText("Evidence evidence-1")).toBeInTheDocument()
    expect(await screen.findByText("Evidence evidence-2")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Load more evidence" })).not.toBeInTheDocument()
  })

  it("continues Originals with the persisted cursor instead of silently stopping at 50", async () => {
    vi.mocked(getLibraryOriginals)
      .mockResolvedValueOnce({
        items: [original("content-1")],
        nextCursor: "original-cursor-2",
      })
      .mockResolvedValueOnce({
        items: [original("content-2")],
        nextCursor: null,
      })
    renderLibrary()

    expect(await screen.findByText("Original content-1")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Load more originals" }))

    await waitFor(() => expect(getLibraryOriginals).toHaveBeenLastCalledWith("original-cursor-2"))
    expect(screen.getByText("Original content-1")).toBeInTheDocument()
    expect(await screen.findByText("Original content-2")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Load more originals" })).not.toBeInTheDocument()
  })

  it("strictly rejects unsafe action and download paths before they can become links", async () => {
    const actual = await vi.importActual<typeof import("@/features/library/api")>("@/features/library/api")
    const exportId = "11111111-1111-4111-8111-111111111111"
    const revisionId = "22222222-2222-4222-8222-222222222222"

    expect(() => actual.decodeLibraryExportPage({
      items: [{
        export_id: exportId,
        status: "succeeded",
        finished_at: "2026-07-13T08:00:00Z",
        artifact: null,
        downloads: ["https://attacker.example/bundle.zip"],
        error_code: null,
        error_message: null,
      }],
      next_cursor: null,
    })).toThrow("Invalid Library export download")

    expect(() => actual.decodeLibraryPublicationPage({
      items: [{
        id: "33333333-3333-4333-8333-333333333333",
        kind: "manual_publication",
        platform: "x",
        revision_id: revisionId,
        occurred_at: "2026-07-13T08:00:00Z",
        status: "manual_published",
        external_url: "https://x.example/post/1",
        action_url: "//attacker.example/review",
      }],
      next_cursor: null,
    })).toThrow("Invalid Library publication action")

    expect(() => actual.decodeLibraryResearchPage({
      items: [{
        id: exportId,
        story_id: revisionId,
        requested_mode: "manual",
        backend: "openrouter",
        status: "failed",
        budget: { max_queries: 4, max_pages: 8, max_elapsed_seconds: 120 },
        created_at: "2026-07-13T08:00:00Z",
        started_at: null,
        finished_at: null,
        attempt_count: 1,
        source_count: 0,
        result_story_revision_id: null,
        error_summary: "redacted failure",
        secret_ref: "env:OPENROUTER_API_KEY",
      }],
      next_cursor: null,
    })).toThrow("Invalid Library research run")

    expect(() => actual.decodeLibraryOriginalPage({
      items: [{
        id: exportId,
        title: "Unsafe original",
        status: "approved",
        source_id: null,
        source_name: null,
        source_url: "javascript:alert(1)",
        published_at: null,
        sort_at: "2026-07-13T08:00:00Z",
      }],
      next_cursor: null,
    })).toThrow("Invalid Library original")
  })

  it("accepts canonical evidence excerpts and rejects clamp-boundary whitespace", async () => {
    const actual = await vi.importActual<typeof import("@/features/library/api")>("@/features/library/api")
    const canonicalExcerpt = "x".repeat(499)
    const payload = {
      id: "11111111-1111-4111-8111-111111111111",
      story_id: "22222222-2222-4222-8222-222222222222",
      content_item_id: null,
      evidence_key: "url:https://source.example/report:" + "a".repeat(64),
      title: "Evidence",
      source_url: "https://source.example/report",
      authors: ["Reporter"],
      published_at: null,
      captured_at: "2026-07-13T08:00:00Z",
      content_sha256: "b".repeat(64),
      excerpt: canonicalExcerpt,
    }

    expect(actual.decodeLibraryEvidencePage({ items: [payload], next_cursor: null }).items[0].excerpt)
      .toBe(canonicalExcerpt)
    expect(() => actual.decodeLibraryEvidencePage({
      items: [{ ...payload, excerpt: canonicalExcerpt + " " }],
      next_cursor: null,
    })).toThrow("Invalid Library evidence snapshot")
  })

  it("keeps a manual publication without an external URL browsable", async () => {
    vi.mocked(getLibraryPublications).mockResolvedValue({
      items: [{
        id: "publication-without-url",
        kind: "manual_publication",
        platform: "blog",
        revisionId: "revision-1",
        occurredAt: "2026-07-13T08:00:00Z",
        status: "manual_published",
        externalUrl: null,
        actionUrl: "/review/revision-1",
      }],
      nextCursor: null,
    })
    renderLibrary()

    fireEvent.click(screen.getByRole("tab", { name: "Publications" }))
    expect(await screen.findByText("Publication URL unavailable.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Review published revision" })).toHaveAttribute(
      "href",
      "/review/revision-1",
    )

    const actual = await vi.importActual<typeof import("@/features/library/api")>("@/features/library/api")
    const revisionId = "22222222-2222-4222-8222-222222222222"
    const decoded = actual.decodeLibraryPublicationPage({
      items: [{
        id: "33333333-3333-4333-8333-333333333333",
        kind: "manual_publication",
        platform: "blog",
        revision_id: revisionId,
        occurred_at: "2026-07-13T08:00:00Z",
        status: "manual_published",
        external_url: null,
        action_url: `/review/${revisionId}`,
      }],
      next_cursor: null,
    })
    expect(decoded.items[0].externalUrl).toBeNull()
  })
})

function renderLibrary() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <LibraryPage />
    </QueryClientProvider>,
  )
}

function evidence(id: string) {
  return {
    id,
    storyId: "story-1",
    contentItemId: "content-1",
    evidenceKey: `key:${id}`,
    title: `Evidence ${id}`,
    sourceUrl: "https://source.example/report",
    authors: ["Reporter"],
    publishedAt: null,
    capturedAt: "2026-07-13T08:00:00Z",
    contentSha256: "a".repeat(64),
    excerpt: "Bounded evidence",
  }
}

function original(id: string) {
  return {
    id,
    title: `Original ${id}`,
    status: "approved",
    sourceId: "source-1",
    sourceName: "Wire Desk",
    sourceUrl: `https://source.example/${id}`,
    publishedAt: "2026-07-13T08:00:00Z",
    sortAt: "2026-07-13T08:00:00Z",
  }
}
