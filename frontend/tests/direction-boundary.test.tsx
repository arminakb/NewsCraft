import { render, screen } from "@testing-library/react"
import { createRef } from "react"

import {
  DirectionBoundary,
  resolveContentDirection,
} from "@/components/newsroom/direction-boundary"

describe("DirectionBoundary", () => {
  beforeEach(() => {
    document.documentElement.setAttribute("lang", "en")
    document.documentElement.setAttribute("dir", "ltr")
  })

  it.each([
    ["fa", "rtl", "گزارش امروز"],
    ["fa-IR", "rtl", "گزارش منطقه‌ای"],
    ["ar-SA", "rtl", "تقرير اليوم"],
    ["en", "ltr", "Today report"],
    ["en-GB", "ltr", "Regional report"],
    ["fr", "ltr", "Rapport du jour"],
  ])("maps language %s to an isolated %s content boundary", (language, direction, text) => {
    render(<DirectionBoundary language={language}>{text}</DirectionBoundary>)

    expect(screen.getByTestId("direction-boundary")).toHaveAttribute("dir", direction)
    expect(screen.getByTestId("direction-boundary")).toHaveAttribute("lang", language)
    expect(document.documentElement).toHaveAttribute("lang", "en")
    expect(document.documentElement).toHaveAttribute("dir", "ltr")
  })

  it.each([null, "", "   ", "und", "UND", "und-Arab"])(
    "uses auto without a misleading lang for unresolved language %p",
    (language) => {
      render(<DirectionBoundary language={language}>2026 — گزارش AI</DirectionBoundary>)

      expect(screen.getByTestId("direction-boundary")).toHaveAttribute("dir", "auto")
      expect(screen.getByTestId("direction-boundary")).not.toHaveAttribute("lang")
      expect(document.documentElement).toHaveAttribute("dir", "ltr")
    },
  )

  it("uses a persisted content-direction override without changing document chrome", () => {
    render(
      <DirectionBoundary as="article" language="en" direction="rtl" aria-label="Persisted Telegram copy">
        متن ذخیره‌شده
      </DirectionBoundary>,
    )

    expect(screen.getByRole("article", { name: "Persisted Telegram copy" })).toHaveAttribute("dir", "rtl")
    expect(screen.getByRole("article", { name: "Persisted Telegram copy" })).toHaveAttribute("lang", "en")
    expect(document.documentElement).toHaveAttribute("dir", "ltr")
  })

  it("forwards semantic element props and styling", () => {
    render(
      <DirectionBoundary as="p" language="fa" className="copy" aria-label="Story copy">
        متن خبر
      </DirectionBoundary>,
    )

    expect(screen.getByLabelText("Story copy")).toHaveClass("copy")
    expect(screen.getByLabelText("Story copy").tagName).toBe("P")
  })

  it("forwards a typed ref to the selected semantic element", () => {
    const ref = createRef<HTMLTextAreaElement>()
    render(<DirectionBoundary as="textarea" language={null} ref={ref} aria-label="Directional editor" />)

    expect(ref.current).toBe(screen.getByRole("textbox", { name: "Directional editor" }))
    ref.current?.focus()
    expect(ref.current).toHaveFocus()
  })

  it("exposes the same normalization for non-visual consumers", () => {
    expect(resolveContentDirection(" ar-EG ")).toEqual({ dir: "rtl", lang: "ar-EG" })
    expect(resolveContentDirection("und")).toEqual({ dir: "auto", lang: undefined })
    expect(resolveContentDirection(null, "ltr")).toEqual({ dir: "ltr", lang: undefined })
  })
})
