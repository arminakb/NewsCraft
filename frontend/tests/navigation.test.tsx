import { fireEvent, render, screen, within } from "@testing-library/react"

import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"

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
    expect(screen.getByRole("link", { name: "Ingestion Runs" })).toHaveAttribute("href", "/runs")
    expect(screen.getByRole("link", { name: "Media" })).toHaveAttribute("href", "/media")
    expect(screen.getByRole("link", { name: "Diagnostics" })).toHaveAttribute("href", "/diagnostics")
    expect(screen.getByRole("link", { name: "Automations" })).toHaveAttribute("href", "/automations")
    expect(screen.getByRole("link", { name: "Drafts" })).toHaveAttribute("href", "/drafts")
    expect(screen.getByRole("link", { name: "Review & Publish" })).toHaveAttribute(
      "href",
      "/drafts?approval_state=pending_review"
    )
    expect(screen.getByRole("link", { name: "Content Settings" })).toHaveAttribute(
      "href",
      "/settings/content"
    )
    expect(screen.getByRole("link", { name: "Content" })).toHaveAttribute("aria-current", "page")

    for (const futureRoute of ["Library"]) {
      expect(screen.queryByRole("link", { name: futureRoute })).not.toBeInTheDocument()
    }
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
    expect(within(dialog).getByRole("link", { name: "Content Settings" })).toHaveAttribute("href", "/settings/content")
  })
})
