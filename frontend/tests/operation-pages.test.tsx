import { render, screen } from "@testing-library/react"

import { DiagnosticsPage } from "@/components/dashboard/pages/diagnostics-page"
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
    getIngestRuns: vi.fn(async () => dashboardMock.runs),
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

  it("renders runs and diagnostics pages", async () => {
    renderWithQuery(<RunsPage initialRuns={dashboardMock.runs} enableQueries={false} />)
    expect(await screen.findByRole("heading", { name: /ingestion runs/i })).toBeInTheDocument()

    renderWithQuery(<DiagnosticsPage />)
    expect(await screen.findByRole("heading", { name: /diagnostics/i })).toBeInTheDocument()
    expect(await screen.findByText("DW Persian")).toBeInTheDocument()
  })
})

function renderWithQuery(ui: React.ReactElement) {
  return render(<QueryProvider>{ui}</QueryProvider>)
}
