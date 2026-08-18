import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"

import { DirtyNavigationCoordinator, useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { SettingsModal } from "@/features/settings/settings-modal"
import {
  SETTINGS_RETURN_PATH_KEY,
  SETTINGS_RESTORE_FOCUS_KEY,
  settingsSections,
} from "@/features/settings/settings-sections"

const push = vi.fn()
const replace = vi.fn()
let searchParams = new URLSearchParams("section=llm-providers")

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useRouter: () => ({ push, replace }),
  useSearchParams: () => searchParams,
}))

vi.mock("@/features/settings/content-settings-page", () => ({
  ContentSettingsPage: ({ section }: { section: string }) => <DirtyPanel section={section} />,
}))

function DirtyPanel({ section }: { section: string }) {
  const [dirty, setDirty] = useState(false)
  useDirtyNavigation(dirty, "Discard unsaved settings changes?")
  return (
    <div>
      <span>Panel: {section}</span>
      <button onClick={() => setDirty((value) => !value)} type="button">
        Toggle unsaved
      </button>
    </div>
  )
}

describe("SettingsModal", () => {
  beforeEach(() => {
    push.mockReset()
    replace.mockReset()
    searchParams = new URLSearchParams("section=llm-providers")
    window.history.replaceState(null, "", "/settings?section=llm-providers")
    window.sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it("renders compact icon categories, active state, and independent panel scrolling", () => {
    render(<SettingsModal />)

    const dialog = screen.getByRole("dialog", { name: "Settings" })
    const navigation = within(dialog).getByRole("navigation", { name: "Settings categories" })
    expect(within(navigation).getAllByRole("button")).toHaveLength(settingsSections.length)
    expect(within(navigation).getByRole("button", { name: "LLM Providers" }))
      .toHaveAttribute("aria-current", "page")
    for (const section of settingsSections) {
      expect(within(navigation).getByRole("button", { name: section.title }).querySelector("svg"))
        .not.toBeNull()
    }
    expect(screen.getByTestId("settings-content-panel")).toHaveClass(
      "overflow-y-auto",
      "overscroll-contain",
    )
    expect(navigation).toHaveClass("overflow-y-auto", "overscroll-contain")
  })

  it("updates URL for every category without reloading", () => {
    render(<SettingsModal />)
    const navigation = screen.getByRole("navigation", { name: "Settings categories" })

    for (const section of settingsSections) {
      fireEvent.click(within(navigation).getByRole("button", { name: section.title }))
      expect(`${window.location.pathname}${window.location.search}`)
        .toBe(`/settings?section=${section.id}`)
    }
    expect(push).not.toHaveBeenCalled()
  })

  it("replaces direct-load section history and the close destination", () => {
    const replaceState = vi.spyOn(window.history, "replaceState")
    const pushState = vi.spyOn(window.history, "pushState")
    render(<SettingsModal />)

    fireEvent.click(screen.getByRole("button", { name: "Date & Time" }))
    expect(replaceState).toHaveBeenLastCalledWith(expect.any(Object), "", "/settings?section=date-time")
    expect(pushState).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole("button", { name: "Close Settings" })[0])
    expect(replace).toHaveBeenCalledWith("/", { scroll: false })
    expect(push).not.toHaveBeenCalled()
  })

  it("canonicalizes missing and invalid section values", () => {
    searchParams = new URLSearchParams("section=unknown")
    render(<SettingsModal />)

    expect(replace).toHaveBeenCalledWith(
      "/settings?section=llm-providers",
      { scroll: false },
    )
    expect(screen.getByText("Panel: llm-providers")).toBeInTheDocument()
  })

  it("closes by button, returns to origin, and requests trigger focus restoration", async () => {
    const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
    window.sessionStorage.setItem(SETTINGS_RETURN_PATH_KEY, "/feed?view=saved")
    render(
      <>
        <button data-settings-trigger type="button">Settings gear</button>
        <SettingsModal />
      </>,
    )

    fireEvent.click(screen.getAllByRole("button", { name: "Close Settings" })[0])
    await waitFor(() => expect(go).toHaveBeenCalledWith(-1))
    expect(push).not.toHaveBeenCalled()
    expect(window.sessionStorage.getItem(SETTINGS_RESTORE_FOCUS_KEY)).toBe("true")
  })

  it("closes with Escape and returns to the remembered origin", async () => {
    const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
    window.sessionStorage.setItem(SETTINGS_RETURN_PATH_KEY, "/jobs")
    render(<SettingsModal />)

    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => {
      expect(go).toHaveBeenLastCalledWith(-1)
    })
  })

  it("blocks category and close actions when unsaved changes are rejected", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    render(<><DirtyNavigationCoordinator /><SettingsModal /></>)

    fireEvent.click(screen.getByRole("button", { name: "Toggle unsaved" }))
    fireEvent.click(screen.getByRole("button", { name: "LLM Providers" }))
    expect(await screen.findByRole("dialog", { name: "Unsaved changes" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    fireEvent.click(screen.getAllByRole("button", { name: "Close Settings" })[0])

    expect(await screen.findByRole("dialog", { name: "Unsaved changes" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(confirm).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
  })

  it("uses full-screen mobile structure with categories first and a visible content Back control", () => {
    const view = render(<SettingsModal />)
    const dialog = screen.getByRole("dialog", { name: "Settings" })

    expect(dialog).toHaveClass("h-dvh", "rounded-none")
    expect(screen.getByRole("navigation", { name: "Settings categories" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Date & Time" }))
    searchParams = new URLSearchParams("section=date-time")
    view.rerender(<SettingsModal />)

    expect(screen.getByRole("button", { name: "Back to Settings categories" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Date & Time" })).toBeInTheDocument()
  })
})
