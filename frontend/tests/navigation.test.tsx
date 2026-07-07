import { render, screen } from "@testing-library/react"

import { AppSidebar } from "@/components/dashboard/app-sidebar"
import { dashboardMock } from "@/lib/mock-data"

vi.mock("next/navigation", () => ({
  usePathname: () => "/content",
}))

describe("AppSidebar", () => {
  it("links to every operational page and marks the current page", () => {
    render(<AppSidebar counts={dashboardMock.counts} />)

    expect(screen.getByRole("link", { name: /overview/i })).toHaveAttribute("href", "/")
    expect(screen.getByRole("link", { name: /sources/i })).toHaveAttribute("href", "/sources")
    expect(screen.getByRole("link", { name: /runs/i })).toHaveAttribute("href", "/runs")
    expect(screen.getByRole("link", { name: /content items/i })).toHaveAttribute("href", "/content")
    expect(screen.getByRole("link", { name: /media/i })).toHaveAttribute("href", "/media")
    expect(screen.getByRole("link", { name: /diagnostics/i })).toHaveAttribute("href", "/diagnostics")
    expect(screen.getByRole("link", { name: /content items/i })).toHaveAttribute("aria-current", "page")
  })
})
