import { fireEvent, render, screen, within } from "@testing-library/react"

import { metadata as settingsMetadata } from "@/app/settings/content/page"
import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"
import { ThemeProvider } from "@/components/providers/theme-provider"
import { packageQueryKeys } from "@/lib/query-keys"

let pathname = "/sources"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

const expectedNavigation = [
  ["Today", "/"],
  ["Sources", "/sources"],
  ["Calendar", "/calendar"],
  ["Library", "/feed"],
  ["Jobs", "/jobs"],
  ["Automations", "/automations"],
  ["Diagnostics", "/diagnostics"],
  ["Retention", "/settings/retention"],
  ["Settings", "/settings/content"],
] as const

describe("NewsroomSidebar", () => {
  beforeEach(() => {
    pathname = "/sources"
  })

  it("exposes every surviving top-level route directly in priority order", () => {
    renderWithTheme(
      <NewsroomSidebar summary={{ queued: 3, running: 1, attention: 2, succeeded_today: 5 }} />,
    )

    const navigation = screen.getByRole("navigation", { name: "Newsroom navigation" })
    const links = within(navigation).getAllByRole("link")

    expect(links.map((link) => link.getAttribute("aria-label"))).toEqual(
      expectedNavigation.map(([label]) => label),
    )
    for (const [label, href] of expectedNavigation) {
      expect(within(navigation).getByRole("link", { name: label })).toHaveAttribute("href", href)
    }
    expect(within(navigation).getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page")
    expect(within(navigation).getByRole("link", { name: "Jobs" })).toHaveAttribute(
      "title",
      "Jobs · 3 queued · 2 need attention",
    )
    expect(screen.getByLabelText("3 queued")).toBeInTheDocument()
    expect(screen.getByLabelText("2 need attention")).toBeInTheDocument()
    expect(within(navigation).getByRole("button", { name: "Toggle color theme" })).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(within(navigation).queryByRole("link", { name: "Drafts" })).not.toBeInTheDocument()
  })

  it("keeps theme control directly above icon-only Settings at the bottom", () => {
    pathname = "/settings/content"
    renderWithTheme(<NewsroomSidebar />)

    const settings = screen.getByRole("link", { name: "Settings" })
    expect(settings).toHaveAttribute("aria-current", "page")
    const controls = settings.closest("[data-sidebar-controls]")
    expect(controls).toHaveClass("mt-auto", "shrink-0", "flex-col")
    expect(controls).not.toHaveClass("border", "border-t", "bg-card")
    expect(controls?.querySelectorAll("button, a")).toHaveLength(2)
    expect(controls?.querySelector("button")).toHaveAccessibleName("Toggle color theme")
    expect(controls?.querySelector("button")?.nextElementSibling?.textContent).toBe("Switch to dark theme")
    expect(controls?.querySelector("button")?.parentElement?.nextElementSibling).toBe(settings.parentElement)
    expect(settings).toHaveClass("size-11")
    expect(settings).not.toHaveTextContent("Settings")
    expect(settings).toHaveAttribute("aria-describedby", "settings-navigation-tooltip")
    expect(screen.getAllByRole("tooltip", { hidden: true }).map((tooltip) => tooltip.textContent)).toEqual([
      "Switch to dark theme",
      "Settings",
    ])
  })

  it("supports vertical arrow, Home, and End keyboard navigation", () => {
    renderWithTheme(<NewsroomSidebar />)

    const aside = screen.getByRole("complementary", { name: "Global navigation" })
    const today = screen.getByRole("link", { name: "Today" })
    const sources = screen.getByRole("link", { name: "Sources" })
    const settings = screen.getByRole("link", { name: "Settings" })

    today.focus()
    fireEvent.keyDown(aside, { key: "ArrowDown" })
    expect(sources).toHaveFocus()
    fireEvent.keyDown(aside, { key: "End" })
    expect(settings).toHaveFocus()
    fireEvent.keyDown(aside, { key: "ArrowDown" })
    expect(today).toHaveFocus()
    fireEvent.keyDown(aside, { key: "Home" })
    expect(today).toHaveFocus()
  })

  it("marks deep operational routes without assigning a false active page", () => {
    pathname = "/settings/retention/history"
    const { rerender } = renderWithTheme(<NewsroomSidebar />)

    expect(screen.getByRole("link", { name: "Retention" })).toHaveAttribute("aria-current", "page")
    expect(screen.getAllByRole("link", { current: "page" })).toHaveLength(1)

    pathname = "/review/revision-1"
    rerender(
      <ThemeProvider>
        <NewsroomSidebar />
      </ThemeProvider>,
    )
    expect(screen.queryByRole("link", { current: "page" })).not.toBeInTheDocument()
  })
})

describe("adaptive mobile navigation", () => {
  it("keeps four primary routes visible and exposes every route in the compact menu", () => {
    pathname = "/sources"
    renderWithTheme(<MobileNewsroomNav />)

    const navigation = screen.getByRole("navigation", { name: "Mobile newsroom navigation" })
    expect(within(navigation).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual(
      expectedNavigation.slice(0, 4).map(([label]) => label),
    )
    expect(within(navigation).getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page")
    fireEvent.click(within(navigation).getByRole("button", { name: "Open navigation" }))

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(within(dialog).getAllByRole("link").map((link) => link.textContent)).toEqual(
      expectedNavigation.map(([label]) => label),
    )
    for (const [label, href] of expectedNavigation) {
      expect(within(dialog).getByRole("link", { name: label })).toHaveAttribute("href", href)
    }
  })

  it("uses Settings route metadata and user-facing name", () => {
    expect(settingsMetadata.title).toBe("Settings | NewsCraft")
  })
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

function renderWithTheme(children: React.ReactNode) {
  return render(<ThemeProvider>{children}</ThemeProvider>)
}
