import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NewsroomShell } from "@/components/newsroom/newsroom-shell"
import { NotificationsSidebar } from "@/components/newsroom/notifications-sidebar"
import type { Notification } from "@/components/ui/notifications-menu"
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
    expect(within(dialog).getByRole("tab", { name: /^All/ })).toBeInTheDocument()
    expect(within(dialog).getByRole("tab", { name: /^Approvals/ })).toBeInTheDocument()
    expect(within(dialog).getByRole("tab", { name: /^Issues/ })).toBeInTheDocument()
    expect(within(dialog).queryByRole("button", { name: "Notification settings" })).not.toBeInTheDocument()
    expect(
      within(dialog).queryByRole("button", { name: /Clear all notifications|Mark all notifications as read/ }),
    ).not.toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("button", { name: "Dismiss Saved" }))
    expect(within(dialog).getByText("We'll let you know when we have news for you.")).toBeInTheDocument()
  })

  it("keeps fixed dimensions across empty, loading, and error states", () => {
    const { rerender } = renderApp(
      <NotificationsSidebar notifications={[]} onOpenChange={() => undefined} open />,
    )
    const emptyDialog = screen.getByRole("dialog", { name: "Your notifications" })
    expect(emptyDialog).toHaveClass(
      "h-[575px]",
      "w-[450px]",
      "max-h-[calc(100dvh-1rem)]",
      "max-w-[calc(100vw-1rem)]",
    )
    expect(within(emptyDialog).getByText("We'll let you know when we have news for you.")).toBeInTheDocument()
    expect(within(emptyDialog).queryByText("Saved")).not.toBeInTheDocument()

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ThemeProvider>
          <NoticeProvider>
            <NotificationsSidebar loading onOpenChange={() => undefined} open />
          </NoticeProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    )
    expect(screen.getByRole("status", { name: /loading notifications/i })).toHaveTextContent("Loading notifications")
    expect(screen.queryByText("Saved")).not.toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: "Your notifications" })).toHaveClass("h-[575px]", "w-[450px]")

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
    expect(screen.getByRole("dialog", { name: "Your notifications" })).toHaveClass("h-[575px]", "w-[450px]")
  })

  it("keeps reference row variants and filters when real records are supplied", async () => {
    const records: Notification[] = [
      {
        action: "commented in",
        content: "Review the latest editorial draft.",
        id: "comment-1",
        isRead: false,
        timeAgo: "2 hours ago",
        timestamp: "Friday 3:12 PM",
        type: "comment",
        user: { avatar: "", fallback: "E", name: "Editor" },
      },
      {
        action: "shared a file in",
        file: { name: "draft.mp4", size: "14 MB", type: "MP4" },
        id: "file-1",
        isRead: true,
        target: "Dashboard 2.0",
        timeAgo: "4 hours ago",
        timestamp: "Friday 1:40 PM",
        type: "file_share",
        user: { avatar: "", fallback: "M", name: "Mathilde" },
      },
      {
        action: "invited you to",
        hasActions: true,
        id: "invite-1",
        isRead: true,
        target: "Blog design",
        timeAgo: "3 hours ago",
        timestamp: "Friday 2:22 PM",
        type: "invitation",
        user: { avatar: "", fallback: "A", name: "Ammar" },
      },
      {
        action: "started following",
        content: "You have a new follower.",
        id: "follow-1",
        isRead: true,
        timeAgo: "5 hours ago",
        timestamp: "Friday 12:40 PM",
        type: "follow",
        user: { avatar: "", fallback: "R", name: "Riley" },
      },
      {
        action: "mentioned you in",
        content: "Please review this mention.",
        id: "mention-1",
        isRead: true,
        target: "Project Alpha",
        timeAgo: "1 day ago",
        timestamp: "Thursday 11:30 AM",
        type: "mention",
        user: { avatar: "", fallback: "J", name: "James" },
      },
    ]

    renderApp(<NotificationsSidebar notifications={records} onOpenChange={() => undefined} open />)
    const dialog = await screen.findByRole("dialog", { name: "Your notifications" })

    expect(within(dialog).getByText("Editor")).toBeInTheDocument()
    expect(dialog.querySelectorAll(".bg-emerald-500")).toHaveLength(1)
    expect(within(dialog).getByText("draft.mp4")).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "Download draft.mp4" })).toBeInTheDocument()
    expect(within(dialog).getByRole("button", { name: "Accept" })).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("tab", { name: /^Approvals/ }))
    expect(within(dialog).getByText("You have a new follower.")).toBeInTheDocument()
    expect(within(dialog).queryByText("Please review this mention.")).not.toBeInTheDocument()
    expect(dialog).toHaveClass("h-[575px]", "w-[450px]")

    fireEvent.click(within(dialog).getByRole("tab", { name: /^Issues/ }))
    expect(within(dialog).getByText("Please review this mention.")).toBeInTheDocument()
    expect(within(dialog).queryByText("draft.mp4")).not.toBeInTheDocument()
    expect(within(dialog).queryByText("You have a new follower.")).not.toBeInTheDocument()
  })

  it("shows an independent empty state for a filter with no matching notifications", async () => {
    const records: Notification[] = [
      {
        action: "needs approval for",
        content: "Review the completed brief.",
        id: "approval-1",
        isRead: false,
        timeAgo: "Just now",
        timestamp: "Just now",
        type: "approval",
        user: { avatar: "", fallback: "N", name: "NewsCraft" },
      },
    ]

    renderApp(<NotificationsSidebar notifications={records} onOpenChange={() => undefined} open />)
    const dialog = await screen.findByRole("dialog", { name: "Your notifications" })
    const popupClassName = dialog.className

    fireEvent.click(within(dialog).getByRole("tab", { name: /^Issues/ }))
    expect(within(dialog).getByText("We'll let you know when we have news for you.")).toBeInTheDocument()
    expect(dialog.className).toBe(popupClassName)

    fireEvent.click(within(dialog).getByRole("tab", { name: /^Approvals/ }))
    expect(within(dialog).getByText("Review the completed brief.")).toBeInTheDocument()
    expect(dialog.className).toBe(popupClassName)
  })

  it("keeps popup surfaces token-driven in dark mode", async () => {
    document.documentElement.classList.add("dark")
    try {
      renderApp(<NewsroomShell><section>Page content</section></NewsroomShell>)
      fireEvent.click(screen.getByRole("button", { name: "Open notifications" }))
      const dialog = await screen.findByRole("dialog", { name: "Your notifications" })
      expect(dialog).toHaveClass("bg-card", "border-border/70")
      expect(dialog).toHaveClass(
        "nc-notifications-popup",
        "h-[575px]",
        "w-[450px]",
        "max-h-[calc(100dvh-1rem)]",
        "max-w-[calc(100vw-1rem)]",
      )
      expect(dialog.querySelector("[data-notifications-scroll]")).toBeInTheDocument()
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
