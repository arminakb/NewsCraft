import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"

import { NoticeProvider, useNotices } from "@/components/providers/notice-provider"
import { getAutomationControl, updateAutomationControl } from "@/features/control/api"
import { GlobalControls } from "@/features/control/global-controls"
import { ApiError } from "@/lib/http"

vi.mock("@/features/control/api", () => ({
  getAutomationControl: vi.fn(),
  updateAutomationControl: vi.fn(),
}))

const activeControl = {
  globalPause: false,
  dryRun: false,
  pauseReason: null,
  pausedAt: null,
  updatedAt: "2026-07-12T08:00:00Z",
}

describe("GlobalControls", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getAutomationControl).mockResolvedValue(activeControl)
    vi.mocked(updateAutomationControl).mockImplementation(async (input) => ({
      ...activeControl,
      globalPause: input.globalPause ?? activeControl.globalPause,
      dryRun: input.dryRun ?? activeControl.dryRun,
      pauseReason: input.pauseReason ?? null,
      pausedAt: input.globalPause ? "2026-07-12T08:01:00Z" : null,
      updatedAt: "2026-07-12T08:01:01Z",
    }))
  })

  it("shows checking and API-error states without inventing a control state", async () => {
    vi.mocked(getAutomationControl).mockImplementation(() => new Promise(() => undefined))
    const first = renderControls()
    expect(screen.getByRole("status", { name: "Checking automation controls" })).toHaveTextContent("Checking automation controls")
    first.unmount()

    vi.mocked(getAutomationControl).mockRejectedValue(new Error("control service offline"))
    renderControls()
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("control service offline")
    expect(alert).toHaveAttribute("dir", "auto")
    expect(screen.queryByRole("button", { name: /pause automations/i })).not.toBeInTheDocument()
  })

  it("sends the exact pause/resume bodies and exposes dry-run state in its accessible name", async () => {
    const { queryClient } = renderControls()
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

    fireEvent.click(await screen.findByRole("button", { name: "Pause automations" }))
    await waitFor(() =>
      expect(updateAutomationControl).toHaveBeenCalledWith({
        globalPause: true,
        pauseReason: "Paused from Newsroom",
      })
    )
    expect(await screen.findByRole("button", { name: "Resume automations" })).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "Dry run is off" })).toBeInTheDocument()
    expect(screen.getByRole("status", { name: "Latest control outcome" })).toHaveTextContent("08:01:01")
    expect(screen.getByText("Automation paused", { selector: "[data-notice-title]" })).toBeInTheDocument()
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["automation-control"] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs", "summary"] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs"] })

    fireEvent.click(screen.getByRole("button", { name: "Resume automations" }))
    await waitFor(() => expect(updateAutomationControl).toHaveBeenLastCalledWith({ globalPause: false }))

    fireEvent.click(screen.getByRole("switch", { name: "Dry run is off" }))
    await waitFor(() => expect(updateAutomationControl).toHaveBeenLastCalledWith({ dryRun: true }))
  })

  it("disables both controls while a mutation is pending", async () => {
    vi.mocked(updateAutomationControl).mockImplementation(() => new Promise(() => undefined))
    renderControls()

    const pause = await screen.findByRole("button", { name: "Pause automations" })
    const dryRun = screen.getByRole("switch", { name: "Dry run is off" })
    fireEvent.click(pause)

    expect(pause).toBeDisabled()
    expect(dryRun).toBeDisabled()
  })

  it("keeps server-derived state unchanged and shows the mutation error", async () => {
    vi.mocked(updateAutomationControl).mockRejectedValue(new Error("pause rejected by API"))
    renderControls()

    fireEvent.click(await screen.findByRole("button", { name: "Pause automations" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("pause rejected by API")
    expect(alert).toHaveAttribute("dir", "auto")
    expect(screen.getByRole("button", { name: "Pause automations" })).toBeInTheDocument()
  })

  it("shows FastAPI detail text from a typed API error", async () => {
    vi.mocked(updateAutomationControl).mockRejectedValue(
      new ApiError("Conflict", 409, JSON.stringify({ detail: "Global pause is locked" }))
    )
    renderControls()

    fireEvent.click(await screen.findByRole("button", { name: "Pause automations" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Global pause is locked")
  })
})

describe("NoticeProvider", () => {
  it("announces notices politely and expires them after five seconds", () => {
    vi.useFakeTimers()
    render(
      <NoticeProvider>
        <NoticeHarness />
      </NoticeProvider>
    )

    fireEvent.click(screen.getByRole("button", { name: "Create notice" }))
    const liveRegion = screen.getByRole("status", { name: "Notifications" })
    expect(liveRegion).toHaveAttribute("aria-live", "polite")
    expect(screen.getByText("Saved")).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(4_999))
    expect(screen.getByText("Saved")).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.queryByText("Saved")).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})

function NoticeHarness() {
  const { pushNotice } = useNotices()
  return (
    <button type="button" onClick={() => pushNotice({ tone: "success", title: "Saved", message: "Control updated" })}>
      Create notice
    </button>
  )
}

function renderControls() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <NoticeProvider>
          <GlobalControls />
        </NoticeProvider>
      </QueryClientProvider>
    ),
  }
}
