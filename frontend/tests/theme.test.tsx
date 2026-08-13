import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { ThemeProvider } from "@/components/providers/theme-provider"
import { ThemeToggle } from "@/components/theme/theme-toggle"
import { THEME_BOOTSTRAP_SCRIPT, THEME_STORAGE_KEY } from "@/lib/theme"

describe("theme foundation", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", createStorage())
    document.documentElement.className = ""
    document.documentElement.removeAttribute("data-theme")
    document.documentElement.style.colorScheme = ""
    vi.stubGlobal("matchMedia", createMatchMedia(false))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("applies a saved theme before hydration", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark")

    runBootstrap()

    expect(document.documentElement).toHaveClass("dark")
    expect(document.documentElement).toHaveAttribute("data-theme", "dark")
    expect(document.documentElement.style.colorScheme).toBe("dark")
  })

  it("uses system preference before hydration when no preference exists", () => {
    vi.stubGlobal("matchMedia", createMatchMedia(true))

    runBootstrap()

    expect(document.documentElement).toHaveClass("dark")
    expect(document.documentElement).toHaveAttribute("data-theme", "dark")
  })

  it("toggles, persists, and exposes theme state accessibly", async () => {
    render(
      <ThemeProvider>
        <ThemeToggle placement="sidebar" />
      </ThemeProvider>,
    )

    const toggle = screen.getByRole("button", { name: "Toggle color theme" })
    await waitFor(() => expect(toggle).toHaveAttribute("aria-pressed", "false"))

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute("aria-pressed", "true")
    expect(toggle).toHaveAttribute("title", "Switch to light theme")
    expect(document.documentElement).toHaveClass("dark")
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark")
  })

  it("defines every Phase 2 semantic role for both themes", () => {
    const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8")
    const requiredTokens = [
      "background",
      "foreground",
      "card",
      "card-foreground",
      "popover",
      "muted",
      "muted-foreground",
      "border",
      "input",
      "primary",
      "primary-foreground",
      "secondary",
      "secondary-foreground",
      "accent",
      "destructive",
      "success",
      "warning",
      "error",
      "ring",
      "navigation-active",
      "navigation-hover",
    ]

    for (const token of requiredTokens) {
      expect(css).toContain(`--${token}:`)
    }
    expect(css).toMatch(/:root\s*{[^}]*color-scheme:\s*light;/s)
    expect(css).toMatch(/\.dark\s*{[^}]*color-scheme:\s*dark;/s)
    expect(css).toMatch(/::selection\s*{/)
    expect(css).toMatch(/:focus-visible\s*{[^}]*var\(--ring\)/s)
  })
})

function runBootstrap() {
  Function(THEME_BOOTSTRAP_SCRIPT)()
}

function createMatchMedia(matches: boolean) {
  return vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

function createStorage(): Storage {
  const values = new Map<string, string>()

  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => {
      values.delete(key)
    },
    setItem: (key, value) => {
      values.set(key, String(value))
    },
  }
}
