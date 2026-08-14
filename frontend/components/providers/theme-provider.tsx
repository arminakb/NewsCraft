"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"

import { isTheme, THEME_STORAGE_KEY, type Theme } from "@/lib/theme"
import { useMediaQuery } from "@/lib/use-media-query"

type ThemeContextValue = {
  theme: Theme | undefined
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>()
  const systemDark = useMediaQuery("(prefers-color-scheme: dark)")

  const chooseTheme = useCallback((nextTheme: Theme, persist: boolean) => {
    applyTheme(nextTheme)
    setTheme(nextTheme)

    if (persist) {
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)
      } catch {
        // Theme still applies for this page when storage is unavailable.
      }
    }
  }, [])

  useEffect(() => {
    const storedTheme = readStoredTheme()
    const initialTheme = storedTheme ?? (systemDark ? "dark" : "light")

    chooseTheme(initialTheme, false)
  }, [chooseTheme, systemDark])

  const toggleTheme = useCallback(() => {
    const currentTheme = theme ?? readAppliedTheme()
    chooseTheme(currentTheme === "dark" ? "light" : "dark", true)
  }, [chooseTheme, theme])

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider")
  }
  return context
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle("dark", theme === "dark")
  root.dataset.theme = theme
  root.style.colorScheme = theme
}

function readAppliedTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light"
}

function readStoredTheme(): Theme | null {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(storedTheme) ? storedTheme : null
  } catch {
    return null
  }
}
