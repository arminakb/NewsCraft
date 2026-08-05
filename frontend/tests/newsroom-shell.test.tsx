import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NewsroomShell } from "@/components/newsroom/newsroom-shell"
import { ThemeProvider } from "@/components/providers/theme-provider"
import { getJobSummary } from "@/features/jobs/api"
import { getDateTimeSettings } from "@/features/settings/date-time-api"

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

const summary = { queued: 3, running: 1, attention: 2, succeeded_today: 5 }

describe("NewsroomShell", () => {
  beforeEach(() => {
    pathname = "/"
    vi.clearAllMocks()
    vi.mocked(getJobSummary).mockResolvedValue(summary)
    vi.mocked(getDateTimeSettings).mockResolvedValue({
      timezone: "Asia/Tehran",
      updatedAt: "2026-07-28T11:00:00Z",
    })
  })

  it("loads the live job summary without rendering a persistent status bar", async () => {
    renderShell()

    expect(await screen.findByLabelText("3 queued")).toBeInTheDocument()
    expect(screen.getByLabelText("2 need attention")).toBeInTheDocument()
    expect(getJobSummary).toHaveBeenCalledTimes(1)
  })

  it("places routed content at the top of the shell without a header wrapper or placeholder", () => {
    renderShell()

    const content = screen.getByTestId("newsroom-content")
    expect(content.firstElementChild).toBe(screen.getByRole("main"))
    expect(content.querySelector("[data-newsroom-header]")).not.toBeInTheDocument()
    expect(screen.queryByRole("timer")).not.toBeInTheDocument()
    expect(screen.queryByText(/automation paused/i)).not.toBeInTheDocument()
  })

  it("exposes primary mobile routes and an accessible compact menu", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 })
    window.dispatchEvent(new Event("resize"))
    renderShell()

    const navigation = screen.getByRole("navigation", { name: "Mobile newsroom navigation" })
    expect(within(navigation).getByRole("link", { name: "Today" })).toBeInTheDocument()
    expect(within(navigation).getByRole("button", { name: "Open navigation" })).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("owns the single main landmark and keeps routed content shrinkable", async () => {
    const { container } = renderShell()

    const main = await screen.findByRole("main")
    expect(main).toHaveAttribute("id", "main-content")
    expect(main).toHaveAttribute("tabindex", "-1")
    expect(main).toHaveClass("min-[900px]:pb-0")
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getByTestId("newsroom-content")).toHaveClass("min-w-0")
    expect(screen.getByTestId("newsroom-content")).toHaveClass("newsroom-scroll", "min-[900px]:overflow-y-auto")
    expect(container.firstElementChild).toHaveClass("min-[900px]:grid")
    expect(container.firstElementChild).toHaveClass("min-[900px]:grid-cols-[72px_minmax(0,1fr)]")
    expect(container.firstElementChild).toHaveClass("min-[900px]:transition-[grid-template-columns]")
    expect(container.firstElementChild).toHaveClass("motion-reduce:min-[900px]:transition-none")
    expect(screen.getByTestId("newsroom-content")).toHaveClass("min-[900px]:col-start-2")
    expect(container.querySelector('[class*="440px"]')).not.toBeInTheDocument()
  })

  it("starts collapsed and exposes keyboard tooltips for every icon-only destination", () => {
    renderShell()

    const sidebar = screen.getByRole("complementary", { name: "Global navigation" })
    const openSidebar = within(sidebar).getByRole("button", { name: "Open sidebar" })
    const today = within(sidebar).getByRole("link", { name: "Today" })

    expect(sidebar).toHaveAttribute("data-sidebar-state", "collapsed")
    expect(sidebar).toHaveClass("min-[900px]:w-[72px]")
    expect(openSidebar).toHaveAttribute("aria-expanded", "false")
    expect(today).toHaveAttribute("aria-describedby", "desktop-today-tooltip")
    expect(within(sidebar).getByRole("tooltip", { name: "Today" })).toBeInTheDocument()
    expect(within(today).getByText("Today")).toHaveAttribute("aria-hidden", "true")
    expect(within(sidebar).getByRole("button", { name: "Toggle color theme" })).toBeInTheDocument()
    expect(within(sidebar).getByRole("link", { name: "Settings" })).toBeInTheDocument()
    expect(sidebar).not.toHaveClass("overflow-x-auto", "overflow-y-auto")
  })

  it("expands from the logo and collapses from the labelled close control", async () => {
    const { container } = renderShell()
    const sidebar = screen.getByRole("complementary", { name: "Global navigation" })

    fireEvent.click(within(sidebar).getByRole("button", { name: "Open sidebar" }))

    expect(sidebar).toHaveAttribute("data-sidebar-state", "expanded")
    expect(sidebar).toHaveClass("min-[900px]:w-[260px]")
    expect(container.firstElementChild).toHaveClass("min-[900px]:grid-cols-[260px_minmax(0,1fr)]")
    expect(within(sidebar).getByText("NewsCraft")).toBeInTheDocument()
    expect(within(sidebar).getByRole("button", { name: "Close sidebar" })).toHaveAttribute(
      "aria-expanded",
      "true",
    )
    expect(within(sidebar).getByRole("button", { name: "Close sidebar" })).toBeInTheDocument()
    expect(within(sidebar).getByRole("tooltip", { name: "Close sidebar" })).toBeInTheDocument()
    expect(within(sidebar).queryByRole("tooltip", { name: "Today" })).not.toBeInTheDocument()
    expect(within(within(sidebar).getByRole("link", { name: "Today" })).getByText("Today"))
      .toHaveAttribute("aria-hidden", "false")
    expect(within(sidebar).getByText("Theme")).toHaveAttribute("aria-hidden", "false")

    fireEvent.click(within(sidebar).getByRole("button", { name: "Close sidebar" }))

    expect(sidebar).toHaveAttribute("data-sidebar-state", "collapsed")
    expect(container.firstElementChild).toHaveClass("min-[900px]:grid-cols-[72px_minmax(0,1fr)]")
    expect(within(sidebar).queryByRole("button", { name: "Close sidebar" })).not.toBeInTheDocument()
    await waitFor(() => {
      expect(within(sidebar).getByRole("button", { name: "Open sidebar" })).toHaveFocus()
    })
  })

  it("preserves active-route semantics and arrow-key navigation in both states", () => {
    pathname = "/operations"
    renderShell()

    const sidebar = screen.getByRole("complementary", { name: "Global navigation" })
    const automations = within(sidebar).getByRole("link", { name: "Automations" })
    const operations = within(sidebar).getByRole("link", { name: "Operations Center" })

    expect(operations).toHaveAttribute("aria-current", "page")
    automations.focus()
    fireEvent.keyDown(automations, { key: "ArrowDown" })
    expect(operations).toHaveFocus()

    fireEvent.click(within(sidebar).getByRole("button", { name: "Open sidebar" }))
    expect(within(sidebar).getByRole("link", { name: "Operations Center" })).toHaveAttribute(
      "aria-current",
      "page",
    )
  })
})

function renderShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NewsroomShell>
          <section aria-label="Routed content">Page content</section>
        </NewsroomShell>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
