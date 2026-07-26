import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"
import { packageQueryKeys } from "@/lib/query-keys"

let pathname = "/sources"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

describe("NewsroomSidebar", () => {
  beforeEach(() => {
    pathname = "/sources"
  })

  it("keeps primary routes in the compact rail and every advanced route in its panel", async () => {
    render(<NewsroomSidebar summary={{ queued: 3, running: 1, attention: 2, succeeded_today: 5 }} />)

    const navigation = screen.getByRole("navigation", { name: "Newsroom navigation" })
    expect(within(navigation).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual([
      "Today",
      "Inbox",
      "Calendar",
      "Library",
    ])

    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute("href", "/inbox")
    expect(screen.getByRole("link", { name: "Calendar" })).toHaveAttribute("href", "/calendar")
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("href", "/feed")
    expect(screen.queryByRole("link", { name: "Feed monitor" })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Content" })).not.toBeInTheDocument()

    const advanced = screen.getByRole("button", { name: /Advanced navigation/ })
    expect(advanced).toHaveAttribute("aria-current", "page")
    expect(advanced).toHaveAttribute("aria-expanded", "false")
    advanced.focus()
    fireEvent.click(advanced)
    const panel = screen.getByRole("dialog", { name: "Advanced navigation" })
    expect(advanced).toHaveAttribute("aria-expanded", "true")
    expect(within(panel).getByText("Automation")).toBeInTheDocument()
    expect(within(panel).getByText("Collection operations")).toBeInTheDocument()
    expect(within(panel).getByText("System")).toBeInTheDocument()
    expect(within(panel).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Job Queue3 queued · 2 attention",
      "Automations",
      "Sources",
      "Ingestion Runs",
      "Diagnostics",
      "Content Settings",
      "Retention",
    ])
    expect(within(panel).getByRole("link", { name: /Job Queue/ })).toHaveAttribute("href", "/jobs")
    expect(within(panel).getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page")
    expect(within(panel).queryByRole("link", { name: /^Content$/ })).not.toBeInTheDocument()
    expect(within(panel).getByRole("link", { name: "Retention" })).toHaveAttribute("href", "/settings/retention")
    await waitFor(() => expect(within(panel).getByRole("link", { name: /Job Queue/ })).toHaveFocus())
    fireEvent.keyDown(panel, { key: "ArrowDown" })
    expect(within(panel).getByRole("link", { name: "Automations" })).toHaveFocus()
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.queryByRole("dialog", { name: "Advanced navigation" })).not.toBeInTheDocument()
    await waitFor(() => expect(advanced).toHaveFocus())
  })

  it("marks Today only at the root path", () => {
    pathname = "/"
    render(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("button", { name: "Advanced navigation" })).not.toHaveAttribute("aria-current")
  })

  it("does not assign removed navigation to exact review work", () => {
    pathname = "/review/revision-1"
    render(<NewsroomSidebar />)

    expect(screen.queryByRole("link", { name: "Drafts" })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { current: "page" })).not.toBeInTheDocument()
  })

  it("marks deep advanced routes and closes the panel on outside press", () => {
    pathname = "/settings/retention/history"
    render(<NewsroomSidebar />)

    const advanced = screen.getByRole("button", { name: "Advanced navigation" })
    expect(advanced).toHaveAttribute("aria-current", "page")
    fireEvent.click(advanced)
    const panel = screen.getByRole("dialog", { name: "Advanced navigation" })
    expect(within(panel).getByRole("link", { name: "Retention" })).toHaveAttribute("aria-current", "page")
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole("dialog", { name: "Advanced navigation" })).not.toBeInTheDocument()
  })

  it("exposes every Telegram workflow and settings link in the scrollable mobile menu", () => {
    render(<MobileNewsroomNav />)
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }))

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(within(dialog).getByText("Workflow")).toBeInTheDocument()
    expect(within(dialog).getByText("Advanced")).toBeInTheDocument()
    expect(within(dialog).getByText("Automation")).toBeInTheDocument()
    expect(within(dialog).getByText("Collection")).toBeInTheDocument()
    expect(within(dialog).getByText("System")).toBeInTheDocument()
    expect(within(dialog).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Today",
      "Inbox",
      "Calendar",
      "Library",
      "Job Queue",
      "Automations",
      "Sources",
      "Ingestion Runs",
      "Diagnostics",
      "Content Settings",
      "Retention",
    ])
    expect(within(dialog).getByRole("link", { name: "Automations" })).toHaveAttribute("href", "/automations")
    expect(within(dialog).getByRole("link", { name: "Inbox" })).toHaveAttribute("href", "/inbox")
    expect(within(dialog).getByRole("link", { name: "Library" })).toHaveAttribute("href", "/feed")
    expect(within(dialog).getByRole("link", { name: "Calendar" })).toHaveAttribute("href", "/calendar")
    expect(within(dialog).getByRole("link", { name: "Content Settings" })).toHaveAttribute("href", "/settings/content")
    expect(within(dialog).getByRole("link", { name: "Retention" })).toHaveAttribute("href", "/settings/retention")
    expect(within(dialog).queryByRole("link", { name: /^Content$/ })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole("link", { name: "Media" })).not.toBeInTheDocument()
  })

  it("uses stable package keys for exports, manual plans, and timezone calendar windows", () => {
    expect(packageQueryKeys.export("export-1")).toEqual(["exports", "export-1"])
    expect(packageQueryKeys.manualPlan("plan-1")).toEqual(["manual-publication-plans", "plan-1"])
    expect(packageQueryKeys.calendar("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", "Asia/Tehran")).toEqual([
      "calendar",
      "2026-07-01T00:00:00Z",
      "2026-08-01T00:00:00Z",
      "Asia/Tehran",
    ])
  })
})
