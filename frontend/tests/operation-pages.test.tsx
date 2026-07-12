import { fireEvent, render, screen } from "@testing-library/react"

import { ContentItemsPage } from "@/components/dashboard/pages/content-items-page"
import { DiagnosticsPage } from "@/components/dashboard/pages/diagnostics-page"
import { MediaAssetsPage } from "@/components/dashboard/pages/media-assets-page"
import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { QueryProvider } from "@/components/providers/query-provider"
import { dashboardMock } from "@/lib/mock-data"

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")
  return {
    ...actual,
    getDashboardSummary: vi.fn(async () => dashboardMock.counts),
    getSources: vi.fn(async () => dashboardMock.sources),
    getContentItem: vi.fn(async () => ({
      ...dashboardMock.queue[0],
      score: 87,
      summary: "Long-form source summary",
      canonicalUrl: "https://example.com/deep-ai",
      status: "approved",
      rewriteBucket: "ready",
      qualityStatus: "strong",
    })),
    getContentItems: vi.fn(async () => dashboardMock.queue),
    getIngestRuns: vi.fn(async () => dashboardMock.runs),
    getMediaAssets: vi.fn(async () => dashboardMock.media),
    getDiagnostics: vi.fn(async () => ({
      status: "ok",
      checks: { database: "ok", sources: "ok" },
      sourceHealth: { healthy: 2, partial: 1, failed: 0, unknown: 0 },
      problemSources: [{ id: "telegram_dw_persian", name: "DW Persian", status: "partial" }],
    })),
  }
})

describe("operational pages", () => {
  it("renders source operations including seeding", async () => {
    const { container } = renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    expect(await screen.findByRole("heading", { name: /sources/i })).toBeInTheDocument()
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument()
    expect(container.querySelector("main")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /seed sources/i })).toBeInTheDocument()
    expect(screen.getAllByText("TechCrunch").length).toBeGreaterThan(0)
  })

  it("renders content operations including approval actions", async () => {
    renderWithQuery(
      <ContentItemsPage
        enableQueries={false}
        initialItems={[
          {
            ...dashboardMock.queue[0],
            score: 87,
            summary: "Long-form source summary",
            canonicalUrl: "https://example.com/deep-ai",
            tags: ["ai", "chips"],
            status: "approved",
            rewriteBucket: "ready",
            isRewriteReady: true,
            rewriteReadyReason: "has summary and image",
            rewriteBlockers: ["needs Persian angle"],
            classificationReasons: ["AI infrastructure topic"],
            sourceTier: "tier_1",
            freshnessBucket: "breaking",
            qualityStatus: "strong",
            scoreBreakdown: { media: 12, source: 25 },
            contentText: "Complete source post body",
            direction: "rtl",
            sourceName: "Source Channel",
            sourcePlatform: "telegram_public",
            authors: ["Source Channel"],
            publishedAt: "2026-07-11T08:00:00Z",
          },
        ]}
      />
    )

    expect(await screen.findByRole("heading", { name: /content items/i })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: /status/i })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: /sort/i })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: /rewrite-ready only/i })).toBeInTheDocument()
    expect(screen.getByText("Score 87")).toBeInTheDocument()
    expect(screen.getByText("Long-form source summary")).toBeInTheDocument()
    expect(screen.getByText("ready")).toBeInTheDocument()
    expect(screen.getByText("strong")).toBeInTheDocument()
    expect(screen.getByText("needs Persian angle")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /view details/i }))
    expect(await screen.findByRole("region", { name: /content item details/i })).toBeInTheDocument()
    expect(screen.getByText("Complete source post body")).toHaveAttribute("dir", "rtl")
    expect(screen.getAllByText("Source Channel")).toHaveLength(2)
    expect(screen.getByText("Telegram")).toBeInTheDocument()
    expect(screen.getByText("2026-07-11T08:00:00Z")).toBeInTheDocument()
    expect(screen.getByText("https://example.com/deep-ai")).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /approve/i }).length).toBeGreaterThan(0)
  })

  it("renders runs, media, and diagnostics pages", async () => {
    renderWithQuery(<RunsPage initialRuns={dashboardMock.runs} enableQueries={false} />)
    expect(await screen.findByRole("heading", { name: /ingestion runs/i })).toBeInTheDocument()

    renderWithQuery(
      <MediaAssetsPage
        enableQueries={false}
        initialMedia={[
          {
            ...dashboardMock.media[0],
            fetchStatus: "downloaded",
            quality: "high",
            confidence: "0.92",
            isPrimaryCandidate: true,
            isPrimary: false,
            sourceType: "article_body",
            role: "hero",
          },
        ]}
      />
    )
    expect(await screen.findByRole("heading", { name: /media assets/i })).toBeInTheDocument()
    expect(screen.getByText("downloaded")).toBeInTheDocument()
    expect(screen.getByText("high")).toBeInTheDocument()
    expect(screen.getByText("article_body")).toBeInTheDocument()
    expect(screen.getByText("hero")).toBeInTheDocument()

    renderWithQuery(<DiagnosticsPage />)
    expect(await screen.findByRole("heading", { name: /diagnostics/i })).toBeInTheDocument()
    expect(await screen.findByText("DW Persian")).toBeInTheDocument()
  })
})

function renderWithQuery(ui: React.ReactElement) {
  return render(<QueryProvider>{ui}</QueryProvider>)
}
