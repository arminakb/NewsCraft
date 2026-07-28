import { Children, isValidElement } from "react"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import RootLayout from "@/app/layout"
import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { NewsroomHeader } from "@/components/newsroom/newsroom-header"
import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"
import { ThemeProvider } from "@/components/providers/theme-provider"

let pathname = "/"

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}))

describe("mobile newsroom navigation", () => {
  beforeEach(() => {
    pathname = "/"
    document.body.style.overflow = ""
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
  })

  it("uses a five-target bottom bar and a compact two-column navigation panel", async () => {
    pathname = "/calendar"
    renderWithTheme(<MobileNewsroomNav />)

    const navigation = screen.getByRole("navigation", { name: "Mobile newsroom navigation" })
    expect(within(navigation).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Today",
      "Sources",
      "Calendar",
      "Library",
    ])
    expect(within(navigation).getByRole("button", { name: "Open navigation" })).toBeInTheDocument()
    expect(within(navigation).getByRole("link", { name: "Calendar" })).toHaveAttribute("aria-current", "page")

    fireEvent.click(within(navigation).getByRole("button", { name: "Open navigation" }))
    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(within(dialog).getByRole("navigation", { name: "Mobile navigation panel" })).toHaveClass(
      "grid-cols-2",
    )
    expect(within(dialog).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Today",
      "Sources",
      "Calendar",
      "Library",
      "Jobs",
      "Automations",
      "Diagnostics",
      "Settings",
    ])
    await waitFor(() => expect(within(dialog).getByRole("link", { name: "Today" })).toHaveFocus())
  })

  it("traps focus, closes on Escape, and restores the menu trigger", async () => {
    renderWithTheme(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    const settings = within(dialog).getByRole("link", { name: "Settings" })
    await waitFor(() => expect(within(dialog).getByRole("link", { name: "Today" })).toHaveFocus())

    settings.focus()
    fireEvent.keyDown(document, { key: "Tab" })
    expect(within(dialog).getByRole("button", { name: "Toggle color theme" })).toHaveFocus()
    fireEvent.keyDown(document, { key: "Escape" })

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(document.body.style.overflow).toBe("")
  })

  it("closes from backdrop and route links without leaving page scroll locked", () => {
    renderWithTheme(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    fireEvent.click(trigger)
    expect(document.body.style.overflow).toBe("hidden")
    fireEvent.click(screen.getByTestId("mobile-navigation-backdrop"))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe("")

    fireEvent.click(trigger)
    window.addEventListener("click", (event) => event.preventDefault(), { capture: true, once: true })
    fireEvent.click(screen.getByRole("dialog").querySelector('a[href="/jobs"]') as HTMLElement)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("switches navigation and header presentation at exactly 900px", () => {
    const { container } = renderWithTheme(
      <>
          <NewsroomSidebar />
          <NewsroomHeader controlState="active" />
          <MobileNewsroomNav />
        </>,
    )

    const sidebar = container.querySelector("aside")
    const header = container.querySelector("header")
    expect(sidebar).toHaveClass("hidden", "min-[900px]:flex", "border-r")
    expect(sidebar).toHaveClass("min-[900px]:col-start-1", "min-[900px]:w-[260px]")
    expect(screen.getByRole("navigation", { name: "Mobile newsroom navigation" })).toHaveClass(
      "min-[900px]:hidden",
    )
    expect(within(header as HTMLElement).getByText("Newsroom Command Center")).toHaveClass("min-[900px]:hidden")
    expect(within(sidebar as HTMLElement).getByRole("img", { name: "NewsCraft" })).toBeInTheDocument()
  })

  it("keeps each mobile bar target at least 44 by 44 pixels", () => {
    renderWithTheme(<MobileNewsroomNav />)

    const navigation = screen.getByRole("navigation", { name: "Mobile newsroom navigation" })
    for (const target of navigation.querySelectorAll("a, button")) {
      expect(target).toHaveClass("min-h-11", "min-w-11")
    }
    expect(navigation).not.toHaveClass("overflow-x-auto", "overflow-y-auto")
  })
})

describe("global shell accessibility", () => {
  it("declares a stable left-to-right document and a skip link to routed content", () => {
    const layout = RootLayout({ children: <div>Routed content</div> })
    const body = Children.toArray(layout.props.children).find(
      (child) => isValidElement(child) && child.type === "body",
    )
    expect(body).toBeDefined()
    if (!isValidElement<{ children?: React.ReactNode }>(body)) return
    const bodyChildren = Children.toArray(body.props.children)
    const head = Children.toArray(layout.props.children).find(
      (child) => isValidElement(child) && child.type === "head",
    )
    const themeScript = isValidElement<{ children?: React.ReactNode }>(head)
      ? Children.toArray(head.props.children).find(
          (child) =>
            isValidElement<{ id?: string }>(child) && child.props.id === "newscraft-theme-init",
        )
      : undefined
    const skipLink = bodyChildren.find(
      (child) =>
        isValidElement<{ href?: string }>(child) && child.type === "a" && child.props.href === "#main-content",
    )

    expect(layout.props.lang).toBe("en")
    expect(layout.props.dir).toBe("ltr")
    expect(themeScript).toBeDefined()
    expect(skipLink).toBeDefined()
    expect(skipLink).toHaveProperty("props.className", "skip-link")
    expect(skipLink).toHaveProperty("props.children", "Skip to content")
  })

  it("keeps focus, overflow, touch, short-height, and reduced-motion safeguards global", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8")

    expect(css).toMatch(/html,\s*body\s*{[^}]*overflow-x:\s*clip;/s)
    expect(css).toMatch(/:focus-visible\s*{[^}]*outline:\s*2px solid var\(--ring\);/s)
    expect(css).toMatch(/\.skip-link:focus-visible\s*{[^}]*transform:\s*translateY\(0\);/s)
    expect(css).toMatch(/@media\s*\(max-width:\s*899px\)/)
    expect(css).toMatch(/@media\s*\(min-width:\s*900px\)\s*and\s*\(max-height:\s*639px\)/)
    expect(css).toMatch(/\.desktop-newsroom-navigation\s*{[^}]*display:\s*none\s*!important;/s)
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
    expect(css).toMatch(/transition-duration:\s*0\.01ms\s*!important;/)
  })
})

function renderWithTheme(children: React.ReactNode) {
  return render(<ThemeProvider>{children}</ThemeProvider>)
}
