import { render, screen } from "@testing-library/react"

import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"

let pathname = "/content"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

describe("NewsroomSidebar", () => {
  beforeEach(() => {
    pathname = "/content"
  })

  it("links only to working Release 1 screens and marks the current page", () => {
    render(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("link", { name: "Job Queue" })).toHaveAttribute("href", "/jobs")
    expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("href", "/sources")
    expect(screen.getByRole("link", { name: "Content" })).toHaveAttribute("href", "/content")
    expect(screen.getByRole("link", { name: "Ingestion Runs" })).toHaveAttribute("href", "/runs")
    expect(screen.getByRole("link", { name: "Media" })).toHaveAttribute("href", "/media")
    expect(screen.getByRole("link", { name: "Diagnostics" })).toHaveAttribute("href", "/diagnostics")
    expect(screen.getByRole("link", { name: "Content" })).toHaveAttribute("aria-current", "page")

    for (const futureRoute of ["Automations", "Drafts", "Review & Publish", "Library"]) {
      expect(screen.queryByRole("link", { name: futureRoute })).not.toBeInTheDocument()
    }
  })

  it("marks Today only at the root path", () => {
    pathname = "/"
    render(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("link", { name: "Content" })).not.toHaveAttribute("aria-current")
  })
})
