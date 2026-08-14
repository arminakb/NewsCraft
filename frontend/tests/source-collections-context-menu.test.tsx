import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import {
  ALL_SOURCES_SCOPE,
  SourceCollectionsPanel,
} from "@/components/dashboard/source-collections-panel"
import type { SourceCollectionSummary, SourcePage } from "@/features/operations/ingestion-api"

const ingestionMocks = vi.hoisted(() => ({
  getSourceCollectionRuns: vi.fn(),
  getSourceCollectionSources: vi.fn(),
  getSourceCollections: vi.fn(),
  getSourcePage: vi.fn(),
  getUnassignedSources: vi.fn(),
}))

vi.mock("@/features/operations/ingestion-api", async () => {
  const actual = await vi.importActual<typeof import("@/features/operations/ingestion-api")>(
    "@/features/operations/ingestion-api",
  )
  return { ...actual, ...ingestionMocks }
})

describe("Source Collection context menu", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    ingestionMocks.getSourceCollections.mockResolvedValue([collection])
    ingestionMocks.getSourcePage.mockResolvedValue(emptyPage)
    ingestionMocks.getUnassignedSources.mockResolvedValue(emptyPage)
    ingestionMocks.getSourceCollectionSources.mockResolvedValue(emptyPage)
    ingestionMocks.getSourceCollectionRuns.mockResolvedValue({ ...emptyPage, items: [] })
  })

  it("keeps system rows plain and opens user Collection actions by pointer or keyboard", async () => {
    const onSelectScope = vi.fn()
    renderPanel(onSelectScope)

    const allSources = screen.getByRole("button", { name: /All Sources/ })
    const systemMenuEvent = createEvent.contextMenu(allSources, { clientX: 20, clientY: 20 })
    fireEvent(allSources, systemMenuEvent)
    expect(systemMenuEvent.defaultPrevented).toBe(false)
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()

    const row = await screen.findByRole("button", { name: /Morning News.*3 sources/ })
    expect(screen.queryByRole("button", { name: "Manage Morning News" })).not.toBeInTheDocument()
    fireEvent.click(row)
    expect(onSelectScope).toHaveBeenCalledWith(collection.id)

    const contextEvent = createEvent.contextMenu(row, { clientX: 120, clientY: 90 })
    fireEvent(row, contextEvent)
    expect(contextEvent.defaultPrevented).toBe(true)
    let menu = screen.getByRole("menu", { name: "Manage Morning News" })
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Edit details",
      "Manage sources",
      "Delete",
    ])
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Edit details" })).toHaveFocus())
    fireEvent.keyDown(menu, { key: "Escape" })
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    await waitFor(() => expect(row).toHaveFocus())

    fireEvent.keyDown(row, { key: "F10", shiftKey: true })
    menu = screen.getByRole("menu", { name: "Manage Morning News" })
    fireEvent.pointerDown(document.body)
    expect(menu).not.toBeInTheDocument()

    row.focus()
    fireEvent.keyDown(row, { key: "ContextMenu" })
    menu = screen.getByRole("menu", { name: "Manage Morning News" })
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Edit details" }))
    const editDialog = await screen.findByRole("dialog", { name: "Edit Source Collection" })
    expect(within(editDialog).getByLabelText("Name")).toHaveValue("Morning News")
    fireEvent.click(within(editDialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(row).toHaveFocus())

    fireEvent.contextMenu(row)
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    const deleteDialog = await screen.findByRole("dialog", { name: "Delete Source Collection?" })
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "Cancel" }))
    expect(row).toBeInTheDocument()
  })
})

function renderPanel(onSelectScope: (scope: string) => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SourceCollectionsPanel
        onSelectScope={onSelectScope}
        selectedScope={ALL_SOURCES_SCOPE}
      >
        {({ onStartIngestion }) => <button onClick={onStartIngestion}>Toolbar ingestion</button>}
      </SourceCollectionsPanel>
    </QueryClientProvider>,
  )
}

const collection: SourceCollectionSummary = {
  id: "44444444-4444-4444-8444-444444444444",
  name: "Morning News",
  description: "Editorial morning run",
  sourceCount: 3,
  maximumSources: 100,
  createdAt: "2026-08-06T08:00:00Z",
  updatedAt: "2026-08-06T08:00:00Z",
  activeIngestRunId: null,
  activeIngestStatus: null,
  activeIngestSourceCount: null,
  activeIngestProcessedCount: null,
  activeIngestSuccessCount: null,
  activeIngestFailureCount: null,
  continuousSubscriptionId: null,
  continuousMode: null,
  continuousStatus: null,
  continuousIntervalMinutes: 15,
  continuousStartedAt: null,
  continuousStoppedAt: null,
  continuousLastCycleAt: null,
  continuousNextCycleAt: null,
  continuousLastSuccessAt: null,
  continuousCycleCount: null,
  continuousLastCycleStatus: null,
  continuousLastError: null,
  continuousCurrentCycleJobId: null,
  continuousCurrentCycleRunId: null,
}

const emptyPage: SourcePage = {
  items: [],
  total: 0,
  limit: 25,
  offset: 0,
  hasMore: false,
}
