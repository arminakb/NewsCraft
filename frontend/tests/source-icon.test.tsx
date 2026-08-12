import { render, screen } from "@testing-library/react"

import { SourceIcon } from "@/components/dashboard/source-icon"

describe("SourceIcon", () => {
  it.each([
    ["SVG", "/sources/svg-source/icon.svg"],
    ["PNG", "/sources/png-source/icon.png"],
    ["ICO-derived", "/sources/ico-source/icon.ico"],
    ["cached", "/sources/cached-source/icon"],
  ])("renders %s resolved logo without a visual tile", (_, iconUrl) => {
    const { container } = render(
      <SourceIcon
        iconUpdatedAt="2026-08-12T10:00:00Z"
        iconUrl={iconUrl}
        name="Publisher"
        platform="rss"
        sourceId="source-1"
      />,
    )

    const image = container.querySelector("img")
    const logoArea = image?.parentElement

    expect(image).toBeInTheDocument()
    expect(image).toHaveClass("object-contain", "p-0.5")
    expect(logoArea).toHaveClass("bg-transparent", "size-7")
    expect(logoArea).not.toHaveClass("bg-background", "border", "shadow-sm")
    expect(screen.queryByLabelText("Publisher source mark")).not.toBeInTheDocument()
  })

  it("keeps initials fallback treatment when no resolved logo exists", () => {
    render(<SourceIcon name="News Craft" platform="rss" />)

    const fallback = screen.getByLabelText("News Craft source mark")

    expect(fallback).toHaveClass("border", "bg-primary/10")
    expect(fallback).toHaveTextContent("NC")
  })
})
