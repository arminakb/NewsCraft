import { fireEvent, render, screen, within } from "@testing-library/react"

import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"
import { packageQueryKeys } from "@/lib/query-keys"

let pathname = "/content"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

describe("NewsroomSidebar", () => {
  beforeEach(() => {
    pathname = "/content"
  })

  it("links to the working newsroom screens and marks the current page", () => {
    render(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("link", { name: "Job Queue" })).toHaveAttribute("href", "/jobs")
    expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("href", "/sources")
    expect(screen.getByRole("link", { name: "Content" })).toHaveAttribute("href", "/content")
    expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute("href", "/inbox")
    expect(screen.getByRole("link", { name: "Ingestion Runs" })).toHaveAttribute("href", "/runs")
    expect(screen.getByRole("link", { name: "Media" })).toHaveAttribute("href", "/media")
    expect(screen.getByRole("link", { name: "Diagnostics" })).toHaveAttribute("href", "/diagnostics")
    expect(screen.getByRole("link", { name: "Automations" })).toHaveAttribute("href", "/automations")
    expect(screen.getByRole("link", { name: "Drafts" })).toHaveAttribute("href", "/drafts")
    expect(screen.getByRole("link", { name: "Review & Publish" })).toHaveAttribute(
      "href",
      "/drafts?approval_state=pending_review"
    )
    expect(screen.getByRole("link", { name: "Calendar" })).toHaveAttribute("href", "/calendar")
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("href", "/library")
    expect(screen.getByRole("link", { name: "Content Settings" })).toHaveAttribute(
      "href",
      "/settings/content"
    )
    expect(screen.getByRole("link", { name: "Retention" })).toHaveAttribute(
      "href",
      "/settings/retention"
    )
    expect(screen.getByRole("link", { name: "Content" })).toHaveAttribute("aria-current", "page")

  })

  it("marks Today only at the root path", () => {
    pathname = "/"
    render(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("link", { name: "Content" })).not.toHaveAttribute("aria-current")
  })

  it("marks Review & Publish while an exact review workspace is open", () => {
    pathname = "/review/revision-1"
    render(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Review & Publish" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("link", { name: "Drafts" })).not.toHaveAttribute("aria-current")
  })

  it("exposes every Telegram workflow and settings link in the scrollable mobile menu", () => {
    render(<MobileNewsroomNav />)
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }))

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(within(dialog).getByRole("link", { name: "Automations" })).toHaveAttribute("href", "/automations")
    expect(within(dialog).getByRole("link", { name: "Drafts" })).toHaveAttribute("href", "/drafts")
    expect(within(dialog).getByRole("link", { name: "Review & Publish" })).toHaveAttribute("href", "/drafts?approval_state=pending_review")
    expect(within(dialog).getByRole("link", { name: "Calendar" })).toHaveAttribute("href", "/calendar")
    expect(within(dialog).getByRole("link", { name: "Library" })).toHaveAttribute("href", "/library")
    expect(within(dialog).getByRole("link", { name: "Content Settings" })).toHaveAttribute("href", "/settings/content")
    expect(within(dialog).getByRole("link", { name: "Retention" })).toHaveAttribute("href", "/settings/retention")
    expect(within(dialog).getByRole("link", { name: "Inbox" })).toHaveAttribute("href", "/inbox")
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
