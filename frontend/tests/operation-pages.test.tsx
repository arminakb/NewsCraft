import { render, screen } from "@testing-library/react"

import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { QueryProvider } from "@/components/providers/query-provider"
import { dashboardMock } from "@/tests/fixtures/dashboard-mock"

vi.mock("@/features/operations/ingestion-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/features/operations/ingestion-api")
  >("@/features/operations/ingestion-api")
  return {
    ...actual,
    getSources: vi.fn(async () => dashboardMock.sources),
    getIngestRuns: vi.fn(async () => dashboardMock.runs),
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

  it("renders the ingestion runs page", async () => {
    renderWithQuery(<RunsPage initialRuns={dashboardMock.runs} enableQueries={false} />)
    expect(await screen.findByRole("heading", { name: /ingestion runs/i })).toBeInTheDocument()
  })
})

function renderWithQuery(ui: React.ReactElement) {
  return render(<QueryProvider>{ui}</QueryProvider>)
}
