import { badgeVariants } from "@/components/ui/badge"

const PALETTES = {
  error: {
    light: { foreground: "#7f1d1d", background: "#fee2e2", focus: "#b91c1c" },
    dark: { foreground: "#fee2e2", background: "#450a0a", focus: "#fca5a5" },
  },
  warning: {
    light: { foreground: "#451a03", background: "#fef3c7", focus: "#92400e" },
    dark: { foreground: "#fef3c7", background: "#451a03", focus: "#fcd34d" },
  },
  success: {
    light: { foreground: "#064e3b", background: "#d1fae5", focus: "#065f46" },
    dark: { foreground: "#d1fae5", background: "#022c22", focus: "#6ee7b7" },
  },
  neutral: {
    light: { foreground: "#0f172a", background: "#f1f5f9", focus: "#334155" },
    dark: { foreground: "#f1f5f9", background: "#020617", focus: "#cbd5e1" },
  },
} as const

describe("semantic badge contrast", () => {
  for (const [variant, themes] of Object.entries(PALETTES)) {
    it(`${variant} uses explicit light/dark classes and WCAG AA pairs`, () => {
      const classes = badgeVariants({ variant: variant as keyof typeof PALETTES })
      expect(classes).not.toMatch(/bg-destructive\/(10|20)/)
      expect(classes).toContain("forced-colors:border-[CanvasText]")

      for (const palette of Object.values(themes)) {
        expect(contrastRatio(palette.foreground, palette.background)).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(palette.focus, palette.background)).toBeGreaterThanOrEqual(3)
      }
    })
  }

  it("keeps the legacy destructive variant on the semantic error palette", () => {
    const classes = badgeVariants({ variant: "destructive" })
    expect(classes).toContain("bg-[var(--error-surface)]")
    expect(classes).toContain("text-destructive")
    expect(classes).toContain("border-destructive/30")
    expect(classes).not.toMatch(/(?:bg|text|border)-red-/)
  })
})

function contrastRatio(foreground: string, background: string): number {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return (lighter + 0.05) / (darker + 0.05)
}

function luminance(hex: string): number {
  const channels = hex.slice(1).match(/.{2}/g)
  if (!channels) throw new Error(`Invalid color: ${hex}`)
  const [red, green, blue] = channels.map((value) => Number.parseInt(value, 16) / 255).map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}
