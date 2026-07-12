import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NewsroomShell } from "@/components/newsroom/newsroom-shell"
import { getAutomationControl } from "@/features/control/api"
import { getJobSummary } from "@/features/jobs/api"

let pathname = "/"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

vi.mock("@/features/control/api", () => ({
  getAutomationControl: vi.fn(),
}))

vi.mock("@/features/jobs/api", () => ({
  getJobSummary: vi.fn(),
}))

const activeControl = {
  globalPause: false,
  dryRun: false,
  pauseReason: null,
  pausedAt: null,
  updatedAt: "2026-07-12T08:00:00Z",
}

const summary = { queued: 3, running: 1, attention: 2, succeededToday: 5 }

describe("NewsroomShell", () => {
  beforeEach(() => {
    pathname = "/"
    vi.clearAllMocks()
    vi.mocked(getAutomationControl).mockResolvedValue(activeControl)
    vi.mocked(getJobSummary).mockResolvedValue(summary)
  })

  it("reports checking controls during the first request without assuming a running state", () => {
    vi.mocked(getAutomationControl).mockImplementation(() => new Promise(() => undefined))

    renderShell()

    expect(screen.getByText("Checking controls")).toBeInTheDocument()
    expect(screen.queryByText(/automation(?:s)? running/i)).not.toBeInTheDocument()
  })

  it("reports an unavailable control request instead of inferring automation state", async () => {
    vi.mocked(getAutomationControl).mockRejectedValue(new Error("offline"))

    renderShell()

    expect(await screen.findByText("Control state unavailable")).toBeInTheDocument()
    expect(screen.queryByText("Automation paused")).not.toBeInTheDocument()
    expect(screen.queryByText(/automation(?:s)? running/i)).not.toBeInTheDocument()
  })

  it("shows a paused state and live job summary only from successful API data", async () => {
    vi.mocked(getAutomationControl).mockResolvedValue({
      ...activeControl,
      globalPause: true,
      pauseReason: "Editorial review",
      pausedAt: "2026-07-12T07:00:00Z",
    })

    renderShell()

    expect(await screen.findByText("Automation paused")).toBeInTheDocument()
    expect(await screen.findByText("3 queued")).toBeInTheDocument()
    expect(screen.getByText("2 need attention")).toBeInTheDocument()
    expect(getAutomationControl).toHaveBeenCalledTimes(1)
    expect(getJobSummary).toHaveBeenCalledTimes(1)
  })

  it("does not show a paused or running claim when the live control is active", async () => {
    renderShell()

    expect(await screen.findByText("Controls available")).toBeInTheDocument()
    expect(screen.queryByText("Automation paused")).not.toBeInTheDocument()
    expect(screen.queryByText(/automation(?:s)? running/i)).not.toBeInTheDocument()
  })

  it("opens mobile navigation, focuses its first link, and restores the trigger on Escape", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
    window.dispatchEvent(new Event("resize"))
    renderShell()
    const trigger = screen.getByRole("button", { name: "Open navigation" })

    expect(screen.getByRole("navigation", { name: "Mobile newsroom navigation" })).toBeInTheDocument()
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    trigger.focus()
    expect(trigger).toHaveFocus()
    fireEvent.click(trigger)

    expect(trigger).toHaveAttribute("aria-expanded", "true")
    const panel = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(panel).toBeInTheDocument()
    await waitFor(() => expect(within(panel).getByRole("link", { name: "Today" })).toHaveFocus())

    fireEvent.keyDown(document, { key: "Escape" })

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(trigger).toHaveFocus()
  })

  it("owns the single main landmark and keeps routed content shrinkable", async () => {
    const { container } = renderShell()

    expect(await screen.findByRole("main")).toHaveAttribute("id", "main-content")
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getByTestId("newsroom-content")).toHaveClass("min-w-0")
    expect(container.querySelector('[class*="440px"]')).not.toBeInTheDocument()
  })
})

function renderShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <NewsroomShell>
        <section aria-label="Routed content">Page content</section>
      </NewsroomShell>
    </QueryClientProvider>
  )
}
