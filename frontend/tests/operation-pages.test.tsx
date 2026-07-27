import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { NoticeProvider } from "@/components/providers/notice-provider"
import { QueryProvider } from "@/components/providers/query-provider"
import { dashboardMock } from "@/tests/fixtures/dashboard-mock"

const ingestionMocks = vi.hoisted(() => ({
  checkSourceHealth: vi.fn(),
  createSource: vi.fn(),
  deleteSource: vi.fn(),
}))

vi.mock("@/features/operations/ingestion-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/features/operations/ingestion-api")
  >("@/features/operations/ingestion-api")
  return {
    ...actual,
    checkSourceHealth: ingestionMocks.checkSourceHealth,
    createSource: ingestionMocks.createSource,
    deleteSource: ingestionMocks.deleteSource,
    getSources: vi.fn(async () => dashboardMock.sources),
    getIngestRuns: vi.fn(async () => dashboardMock.runs),
  }
})

describe("operational pages", () => {
  beforeEach(() => {
    ingestionMocks.checkSourceHealth.mockReset()
    ingestionMocks.createSource.mockReset()
    ingestionMocks.deleteSource.mockReset()
    ingestionMocks.createSource.mockResolvedValue({
      ...dashboardMock.sources[0],
      id: "persisted-source-1",
      name: "Example Wire",
      url: "https://example.com/feed.xml",
      status: "unknown",
    })
    ingestionMocks.deleteSource.mockResolvedValue(undefined)
  })

  it("runs an individual source health check and updates its row", async () => {
    ingestionMocks.checkSourceHealth.mockResolvedValueOnce({
      sourceId: dashboardMock.sources[0].id,
      status: "broken",
      isChecking: false,
      lastCheckedAt: "2026-07-27T08:30:00Z",
      failureReason: "Source returned HTTP 503.",
    })
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /check techcrunch health, currently healthy/i }))

    expect(await screen.findByRole("button", { name: /check techcrunch health, currently broken/i })).toBeInTheDocument()
    expect(screen.getAllByText("Source returned HTTP 503.").length).toBeGreaterThan(0)
    expect(ingestionMocks.checkSourceHealth).toHaveBeenCalledWith(dashboardMock.sources[0].id)
  })

  it("checks all sources with bounded concurrency and progressive updates", async () => {
    const sources = Array.from({ length: 6 }, (_, index) => ({
      ...dashboardMock.sources[0],
      id: `source-${index}`,
      name: `Source ${index}`,
    }))
    const pending = new Map<string, {
      reject: (error: Error) => void
      resolve: (value: {
        sourceId: string
        status: "healthy" | "broken"
        isChecking: false
        lastCheckedAt: string
        failureReason: string | null
      }) => void
    }>()
    ingestionMocks.checkSourceHealth.mockImplementation((sourceId: string) =>
      new Promise((resolve, reject) => {
        pending.set(sourceId, { resolve, reject })
      })
    )
    renderWithQuery(<SourcesPage initialSources={sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /check all source health/i }))

    await waitFor(() => expect(ingestionMocks.checkSourceHealth).toHaveBeenCalledTimes(4))
    await act(async () => {
      pending.get("source-0")?.resolve({
        sourceId: "source-0",
        status: "broken",
        isChecking: false,
        lastCheckedAt: "2026-07-27T08:30:00Z",
        failureReason: "Invalid response.",
      })
    })
    expect(await screen.findByRole("button", { name: /check source 0 health, currently broken/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /checking all source health/i })).toBeDisabled()
    await waitFor(() => expect(ingestionMocks.checkSourceHealth).toHaveBeenCalledTimes(5))

    await act(async () => {
      pending.get("source-1")?.reject(new Error("Backend timeout"))
      for (const sourceId of ["source-2", "source-3", "source-4"]) {
        pending.get(sourceId)?.resolve({
          sourceId,
          status: "healthy",
          isChecking: false,
          lastCheckedAt: "2026-07-27T08:30:00Z",
          failureReason: null,
        })
      }
    })
    await waitFor(() => expect(ingestionMocks.checkSourceHealth).toHaveBeenCalledTimes(6))
    await act(async () => {
      pending.get("source-5")?.resolve({
        sourceId: "source-5",
        status: "healthy",
        isChecking: false,
        lastCheckedAt: "2026-07-27T08:30:00Z",
        failureReason: null,
      })
    })

    expect(await screen.findByRole("button", { name: /check all source health/i })).toBeEnabled()
    expect(screen.getByText("Source health checks finished with errors")).toBeInTheDocument()
  })

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

  it("closes and reopens details for the selected source", async () => {
    renderWithQuery(
      <SourcesPage
        initialSources={dashboardMock.sources}
        enableQueries={false}
        initialSourceId={dashboardMock.sources[0].id}
      />
    )

    expect(screen.getByRole("region", { name: /source details/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /close source details/i }))

    expect(screen.queryByRole("region", { name: /source details/i })).not.toBeInTheDocument()
    const reopen = screen.getByRole("button", { name: /show techcrunch source details/i })
    fireEvent.click(reopen)

    expect(screen.getByRole("region", { name: /source details/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "TechCrunch" })).toBeInTheDocument()
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

    await waitFor(() => {
      expect(ingestionMocks.createSource).toHaveBeenCalledWith(expect.objectContaining({
        name: "Example Wire",
        url: "https://example.com/feed.xml",
      }), expect.anything())
    })
    expect(await screen.findByRole("row", { name: /example wire/i })).toBeInTheDocument()
    expect(screen.queryByRole("dialog", { name: /add source/i })).not.toBeInTheDocument()
    expect(await screen.findByText("Source added")).toBeInTheDocument()
  })

  it("keeps the add dialog open when persistent creation fails", async () => {
    ingestionMocks.createSource.mockRejectedValueOnce(new Error("Database unavailable"))
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /add source/i }))
    const dialog = screen.getByRole("dialog", { name: /add source/i })
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Example Wire" } })
    fireEvent.change(within(dialog).getByLabelText("Feed URL"), {
      target: { value: "https://example.com/feed.xml" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Add source" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Database unavailable")
    expect(screen.getByRole("dialog", { name: /add source/i })).toBeInTheDocument()
    expect(screen.queryByRole("row", { name: /example wire/i })).not.toBeInTheDocument()
  })

  it("confirms before deleting an existing source", async () => {
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /delete techcrunch/i }))
    const dialog = screen.getByRole("dialog", { name: /delete source/i })
    expect(dialog).toHaveTextContent("TechCrunch")
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete source" }))

    await waitFor(() => {
      expect(ingestionMocks.deleteSource).toHaveBeenCalledWith(dashboardMock.sources[0].id)
    })
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /techcrunch/i })).not.toBeInTheDocument()
    })
    expect(await screen.findByText("Source deleted")).toBeInTheDocument()
  })

  it("shows a loading state while persistent deletion is pending", async () => {
    let resolveDelete: (() => void) | undefined
    ingestionMocks.deleteSource.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        resolveDelete = resolve
      })
    )
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /delete techcrunch/i }))
    const dialog = screen.getByRole("dialog", { name: /delete source/i })
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete source" }))

    expect(await within(dialog).findByRole("button", { name: /deleting techcrunch/i })).toBeDisabled()
    expect(screen.getByRole("row", { name: /techcrunch/i })).toBeInTheDocument()

    await act(async () => {
      resolveDelete?.()
    })
    await waitFor(() => {
      expect(screen.queryByRole("row", { name: /techcrunch/i })).not.toBeInTheDocument()
    })
  })

  it("keeps the source visible and reports a persistent deletion failure", async () => {
    ingestionMocks.deleteSource.mockRejectedValueOnce(new Error("Database unavailable"))
    renderWithQuery(<SourcesPage initialSources={dashboardMock.sources} enableQueries={false} />)

    fireEvent.click(screen.getByRole("button", { name: /delete techcrunch/i }))
    const dialog = screen.getByRole("dialog", { name: /delete source/i })
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete source" }))

    expect(await screen.findByText("Source deletion failed")).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("Database unavailable")
    expect(screen.getByRole("row", { name: /techcrunch/i })).toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: /delete source/i })).toBeInTheDocument()
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
