import { fireEvent, render, screen, within } from "@testing-library/react"

import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { NoticeProvider } from "@/components/providers/notice-provider"
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
    expect(screen.getByRole("button", { name: /add source/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /run ingest/i })).not.toBeInTheDocument()
    expect(screen.getAllByText("TechCrunch").length).toBeGreaterThan(0)
  })

  it("keeps the Sources page responsive while switching source types", async () => {
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(await screen.findByRole("tab", { name: /rss 1/i }))
    expect(screen.getByRole("row", { name: /techcrunch/i })).toBeInTheDocument()
    expect(screen.queryByRole("row", { name: /dw persian/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: /telegram 1/i }))
    expect(screen.getByRole("row", { name: /dw persian/i })).toBeInTheDocument()
    expect(screen.queryByRole("row", { name: /techcrunch/i })).not.toBeInTheDocument()
  })

  it("adds an RSS source from the management dialog", async () => {
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /add source/i }))
    const dialog = screen.getByRole("dialog", { name: /add source/i })
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Example Wire" } })
    fireEvent.change(within(dialog).getByLabelText("Feed URL"), {
      target: { value: "https://example.com/feed.xml" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Add source" }))

    expect(screen.queryByRole("dialog", { name: /add source/i })).not.toBeInTheDocument()
    expect(screen.getByRole("row", { name: /example wire/i })).toBeInTheDocument()
    expect(await screen.findByText("Source added")).toBeInTheDocument()
  })

  it("confirms before deleting an existing source", async () => {
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /delete techcrunch/i }))
    const dialog = screen.getByRole("dialog", { name: /delete source/i })
    expect(dialog).toHaveTextContent("TechCrunch")
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete source" }))

    expect(screen.queryByRole("row", { name: /techcrunch/i })).not.toBeInTheDocument()
    expect(await screen.findByText("Source deleted")).toBeInTheDocument()
  })

  it("renders the ingestion runs page", async () => {
    renderWithQuery(<RunsPage initialRuns={dashboardMock.runs} enableQueries={false} />)
    expect(await screen.findByRole("heading", { name: /ingestion runs/i })).toBeInTheDocument()
  })
})

function renderWithQuery(ui: React.ReactElement) {
  return render(
    <QueryProvider>
      <NoticeProvider>{ui}</NoticeProvider>
    </QueryProvider>
  )
}
