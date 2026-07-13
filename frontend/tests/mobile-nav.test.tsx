import { Children, isValidElement } from "react"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import RootLayout from "@/app/layout"
import { MobileNewsroomNav } from "@/components/newsroom/mobile-newsroom-nav"
import { NewsroomHeader } from "@/components/newsroom/newsroom-header"
import { NewsroomSidebar } from "@/components/newsroom/newsroom-sidebar"

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

  it("is an aria-modal drawer with initial focus and current-page state", async () => {
    pathname = "/inbox"
    render(<MobileNewsroomNav />)

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }))

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(within(dialog).getByRole("link", { name: "Inbox" })).toHaveAttribute("aria-current", "page")
    await waitFor(() => expect(within(dialog).getByRole("link", { name: "Today" })).toHaveFocus())
  })

  it("wraps Tab and Shift-Tab inside the open drawer", async () => {
    render(<MobileNewsroomNav />)
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }))

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    const closeButton = within(dialog).getByRole("button", { name: "Close navigation" })
    const lastLink = within(dialog).getByRole("link", { name: "Retention" })
    await waitFor(() => expect(within(dialog).getByRole("link", { name: "Today" })).toHaveFocus())

    lastLink.focus()
    fireEvent.keyDown(document, { key: "Tab" })
    expect(closeButton).toHaveFocus()

    closeButton.focus()
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true })
    expect(lastLink).toHaveFocus()
  })

  it("closes on Escape and restores focus to the menu trigger", async () => {
    render(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    await waitFor(() => expect(within(dialog).getByRole("link", { name: "Today" })).toHaveFocus())

    fireEvent.keyDown(document, { key: "Escape" })

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("closes from the backdrop and restores focus to the menu trigger", () => {
    render(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    fireEvent.click(trigger)

    fireEvent.click(screen.getByTestId("mobile-navigation-backdrop"))

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("closes from its close control and restores focus to the menu trigger", () => {
    render(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    fireEvent.click(trigger)

    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }))

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("closes from a destination link and restores focus while navigation starts", () => {
    render(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    fireEvent.click(trigger)

    const dialog = screen.getByRole("dialog", { name: "Newsroom navigation" })
    window.addEventListener("click", (event) => event.preventDefault(), { capture: true, once: true })
    fireEvent.click(within(dialog).getByRole("link", { name: "Inbox" }))

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("locks page scrolling only while mounted open and restores it during cleanup", () => {
    document.body.style.overflow = "scroll"
    const { unmount } = render(<MobileNewsroomNav />)
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }))

    expect(document.body.style.overflow).toBe("hidden")

    unmount()
    expect(document.body.style.overflow).toBe("scroll")
  })

  it("closes and restores focus when the viewport crosses into desktop navigation", () => {
    render(<MobileNewsroomNav />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    fireEvent.click(trigger)

    Object.defineProperty(window, "innerWidth", { configurable: true, value: 900 })
    fireEvent(window, new Event("resize"))

    expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
    expect(document.body.style.overflow).toBe("")
    expect(trigger).toHaveFocus()
  })

  it("switches navigation and header presentation at exactly 900px", () => {
    const { container } = render(
      <>
        <NewsroomSidebar />
        <NewsroomHeader controlState="active" />
        <MobileNewsroomNav />
      </>
    )

    const sidebar = container.querySelector("aside")
    const header = container.querySelector("header")
    expect(sidebar).toHaveClass("hidden", "min-[900px]:flex")
    expect(screen.getByRole("navigation", { name: "Mobile newsroom navigation" })).toHaveClass(
      "min-[900px]:hidden"
    )
    expect(within(header as HTMLElement).getByText("Newsroom Command Center")).toHaveClass("min-[900px]:hidden")
    expect(within(header as HTMLElement).getByText("NewsCraft")).toHaveClass("min-[900px]:text-lg")
    expect(within(sidebar as HTMLElement).getByText("Newsroom Command Center")).toHaveClass("text-slate-600")
  })

  it("keeps every primary mobile navigation target at least 44 by 44 pixels", () => {
    render(<MobileNewsroomNav />)

    const mobileNavigation = screen.getByRole("navigation", { name: "Mobile newsroom navigation" })
    for (const target of mobileNavigation.querySelectorAll("a, button")) {
      expect(target).toHaveClass("min-h-11", "min-w-11")
    }
  })
})

describe("global shell accessibility", () => {
  it("declares a stable left-to-right document and a skip link to routed content", () => {
    const layout = RootLayout({ children: <div>Routed content</div> })
    const body = layout.props.children
    const bodyChildren = Children.toArray(body.props.children)
    const skipLink = bodyChildren.find(
      (child) =>
        isValidElement<{ href?: string }>(child) && child.type === "a" && child.props.href === "#main-content"
    )

    expect(layout.props.lang).toBe("en")
    expect(layout.props.dir).toBe("ltr")
    expect(skipLink).toBeDefined()
    expect(skipLink).toHaveProperty("props.className", "skip-link")
    expect(skipLink).toHaveProperty("props.children", "Skip to content")
  })

  it("keeps focus, overflow, touch, skip-link, and reduced-motion safeguards global", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8")

    expect(css).toMatch(/html,\s*body\s*{[^}]*overflow-x:\s*clip;/s)
    expect(css).toMatch(/:focus-visible\s*{[^}]*outline:\s*2px solid var\(--primary\);/s)
    expect(css).toMatch(/\.skip-link\s*{/)
    expect(css).toMatch(/\.skip-link:focus-visible\s*{[^}]*transform:\s*translateY\(0\);/s)
    expect(css).toMatch(/@media\s*\(max-width:\s*899px\)/)
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
    expect(css).toMatch(/animation-duration:\s*0\.01ms\s*!important;/)
    expect(css).toMatch(/transition-duration:\s*0\.01ms\s*!important;/)
  })
})
