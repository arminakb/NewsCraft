import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NewsroomShell } from "@/components/newsroom/newsroom-shell"
import { NotificationsSidebar } from "@/components/newsroom/notifications-sidebar"
import { NoticeProvider, useNotices } from "@/components/providers/notice-provider"
import { ThemeProvider } from "@/components/providers/theme-provider"
import { getDateTimeSettings } from "@/features/settings/date-time-api"
import { getJobSummary } from "@/features/jobs/api"

let pathname = "/"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

vi.mock("@/features/jobs/api", () => ({
  getJobSummary: vi.fn(),
}))

vi.mock("@/features/settings/date-time-api", () => ({
  getDateTimeSettings: vi.fn(),
}))

describe("notifications sidebar", () => {
  beforeEach(() => {
    pathname = "/"
    vi.clearAllMocks()
    vi.mocked(getJobSummary).mockResolvedValue({ queued: 0, running: 0, attention: 0, succeeded_today: 0 })
    vi.mocked(getDateTimeSettings).mockResolvedValue({
      timezone: "Asia/Tehran",
      updatedAt: "2026-08-05T10:00:00Z",
    })
  })

  it("opens from the bell without changing the URL and restores focus after close", async () => {
    renderApp(<NewsroomShell><section>Page content</section></NewsroomShell>)

    const trigger = screen.getByRole("button", { name: "Open notifications" })
    const initialPath = window.location.pathname
    fireEvent.click(trigger)

    const dialog = await screen.findByRole("dialog", { name: "Your notifications" })
    expect(window.location.pathname).toBe(initialPath)
    expect(trigger).toHaveAttribute("aria-expanded", "true")
    expect(within(dialog).getByRole("button", { name: "Close notifications" })).toHaveFocus()

    fireEvent.click(within(dialog).getByRole("button", { name: "Close notifications" }))
    await waitFor(() => expect(trigger).toHaveFocus())
    expect(screen.queryByRole("dialog", { name: "Your notifications" })).not.toBeInTheDocument()

    fireEvent.click(trigger)
    await screen.findByRole("dialog", { name: "Your notifications" })
    fireEvent.click(document.querySelector(".nc-dialog-scrim") as HTMLElement)
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Your notifications" })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()

    fireEvent.click(trigger)
    await screen.findByRole("dialog", { name: "Your notifications" })
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Your notifications" })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it("reuses active in-app notices, filters them, and supports scrolling and dismissal", async () => {
    renderApp(
      <>
        <NoticeHarness />
        <NewsroomShell><section>Page content</section></NewsroomShell>
      </>,
    )

    fireEvent.click(screen.getByRole("button", { name: "Create success notice" }))
    fireEvent.click(screen.getByRole("button", { name: "Open notifications" }))

    const dialog = await screen.findByRole("dialog", { name: "Your notifications" })
    expect(within(dialog).getByText("Saved")).toBeInTheDocument()
    expect(dialog.querySelector(".overflow-y-auto")).toHaveClass("overscroll-contain")
    expect(within(dialog).getByRole("tab", { name: /Success/ })).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("button", { name: "Dismiss Saved" }))
    expect(within(dialog).getByText("No notifications yet.")).toBeInTheDocument()
  })

  it("shows loading, empty, and error states without inventing rows", () => {
    const { rerender } = renderApp(
      <NotificationsSidebar loading onOpenChange={() => undefined} open />,
    )
    expect(screen.getByRole("status", { name: /loading notifications/i })).toHaveTextContent("Loading notifications")
    expect(screen.queryByText("Saved")).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ThemeProvider>
          <NoticeProvider>
            <NotificationsSidebar error="Notification service unavailable" onOpenChange={() => undefined} open />
          </NoticeProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    )
    expect(screen.getByRole("alert")).toHaveTextContent("Notification service unavailable")
  })

  it("keeps drawer surfaces token-driven in dark mode", async () => {
    document.documentElement.classList.add("dark")
    try {
      renderApp(<NewsroomShell><section>Page content</section></NewsroomShell>)
      fireEvent.click(screen.getByRole("button", { name: "Open notifications" }))
      const dialog = await screen.findByRole("dialog", { name: "Your notifications" })
      expect(dialog).toHaveClass("bg-card", "border-border/70")
      expect(document.querySelector(".nc-dialog-scrim")).toHaveClass("nc-dialog-scrim")
    } finally {
      document.documentElement.classList.remove("dark")
    }
  })
})

function NoticeHarness() {
  const { pushNotice } = useNotices()
  return (
    <button
      type="button"
      onClick={() => pushNotice({ tone: "success", title: "Saved", message: "Control updated." })}
    >
      Create success notice
    </button>
  )
}

function renderApp(children: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ThemeProvider>
        <NoticeProvider>{children}</NoticeProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}
