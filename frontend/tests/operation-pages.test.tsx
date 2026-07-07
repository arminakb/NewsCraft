import { render, screen } from "@testing-library/react"

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
    getSources: vi.fn(async () => dashboardMock.sources),
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
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} />)

    expect(await screen.findByRole("heading", { name: /sources/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /seed sources/i })).toBeInTheDocument()
    expect(screen.getAllByText("TechCrunch").length).toBeGreaterThan(0)
  })

  it("renders content operations including approval actions", async () => {
    renderWithQuery(<ContentItemsPage initialItems={dashboardMock.queue} />)

    expect(await screen.findByRole("heading", { name: /content items/i })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: /status/i })).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: /sort/i })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: /rewrite-ready only/i })).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /approve/i }).length).toBeGreaterThan(0)
  })

  it("renders runs, media, and diagnostics pages", async () => {
    renderWithQuery(<RunsPage initialRuns={dashboardMock.runs} />)
    expect(await screen.findByRole("heading", { name: /ingestion runs/i })).toBeInTheDocument()

    renderWithQuery(<MediaAssetsPage initialMedia={dashboardMock.media} />)
    expect(await screen.findByRole("heading", { name: /media assets/i })).toBeInTheDocument()

    renderWithQuery(<DiagnosticsPage />)
    expect(await screen.findByRole("heading", { name: /diagnostics/i })).toBeInTheDocument()
    expect(await screen.findByText("DW Persian")).toBeInTheDocument()
  })
})

function renderWithQuery(ui: React.ReactElement) {
  return render(<QueryProvider>{ui}</QueryProvider>)
}
