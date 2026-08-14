import { fireEvent, render, screen, within } from "@testing-library/react"

import { metadata as settingsMetadata } from "@/app/settings/content/page"
import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { isCurrentPath, NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"
import { ThemeProvider } from "@/components/providers/theme-provider"
import { packageQueryKeys } from "@/lib/query-keys"

let pathname = "/sources"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

const expectedNavigation = [
  ["Today", "/"],
  ["Sources", "/sources"],
  ["Feed", "/feed"],
  ["Automations", "/automations"],
  ["Operations Center", "/operations"],
  ["Settings", "/settings?section=llm-providers"],
] as const

describe("NewsroomSidebar", () => {
  beforeEach(() => {
    pathname = "/sources"
  })

  it("matches navigation hrefs by pathname when they include a query", () => {
    expect(isCurrentPath("/settings", "/settings?section=llm-providers")).toBe(true)
    expect(isCurrentPath("/settings/profile", "/settings?section=llm-providers")).toBe(true)
    expect(isCurrentPath("/feed", "/settings?section=llm-providers")).toBe(false)
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
      const link = within(navigation).getByRole("link", { name: label })
      expect(link).toHaveAttribute("href", href)
      expect(link).toHaveClass("min-h-11")
      expect(link).toHaveClass(label === "Settings" ? "min-w-11" : "size-11")
    }
    expect(within(navigation).getByRole("link", { name: "Sources" })).toHaveAttribute(
      "aria-current",
      "page",
    )
    expect(within(navigation).getByRole("link", { name: "Operations Center" })).toHaveAttribute(
      "aria-describedby",
      "desktop-operations-tooltip",
    )
    expect(within(navigation).getByRole("tooltip", { name: "Operations Center" })).toBeInTheDocument()
    expect(screen.getByLabelText("3 queued")).toBeInTheDocument()
    expect(screen.getByLabelText("2 need attention")).toBeInTheDocument()
    expect(within(navigation).getByRole("button", { name: "Toggle color theme" })).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(within(navigation).queryByRole("link", { name: "Drafts" })).not.toBeInTheDocument()
  })

  it("keeps theme and Settings controls at the bottom", () => {
    pathname = "/settings"
    renderWithTheme(<NewsroomSidebar />)

    const settings = screen.getByRole("link", { name: "Settings" })
    expect(settings).toHaveAttribute("aria-current", "page")
    const controls = settings.closest("[data-sidebar-controls]")
    expect(controls).toHaveClass("mt-auto", "shrink-0", "flex-col")
    expect(controls).not.toHaveClass("border", "border-t", "bg-card")
    expect(controls?.querySelectorAll("button, a")).toHaveLength(3)
    const themeButton = within(controls as HTMLElement).getByRole("button", { name: "Toggle color theme" })
    expect(themeButton.nextElementSibling?.textContent).toBe("Switch to dark theme")
    expect(themeButton.parentElement?.nextElementSibling).toBe(settings.parentElement)
    expect(settings).toHaveClass("min-h-11", "min-w-11")
    expect(within(settings).getByText("Settings")).toHaveAttribute("aria-hidden", "true")
    expect(settings).toHaveAttribute("aria-describedby", "desktop-settings-tooltip")
    expect(within(controls as HTMLElement).getAllByRole("tooltip", { hidden: true }).map((tooltip) => tooltip.textContent)).toEqual([
      "Notifications",
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

  it("does not assign a false active page on unrelated deep routes", () => {
    pathname = "/review/revision-1"
    const { rerender } = renderWithTheme(<NewsroomSidebar />)

    expect(screen.queryByRole("link", { current: "page" })).not.toBeInTheDocument()

    pathname = "/settings"
    rerender(
      <ThemeProvider>
        <NewsroomSidebar />
      </ThemeProvider>,
    )
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page")
  })
})

describe("adaptive mobile navigation", () => {
  it("keeps three primary routes visible and exposes every route in the compact menu", () => {
    pathname = "/sources"
    renderWithTheme(<MobileNewsroomNav />)

    const navigation = screen.getByRole("navigation", { name: "Mobile newsroom navigation" })
    expect(within(navigation).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual(
      expectedNavigation.slice(0, 3).map(([label]) => label),
    )
    expect(within(navigation).getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page")
    fireEvent.click(within(navigation).getByRole("button", { name: "Open navigation" }))

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(within(dialog).getAllByRole("link").map((link) => link.textContent).filter(Boolean)).toEqual(
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

it("uses stable package keys for exports and manual plans", () => {
  expect(packageQueryKeys.export("export-1")).toEqual(["exports", "export-1"])
  expect(packageQueryKeys.manualPlan("plan-1")).toEqual(["manual-publication-plans", "plan-1"])
})

function renderWithTheme(children: React.ReactNode) {
  return render(<ThemeProvider>{children}</ThemeProvider>)
}
