import { render, screen } from "@testing-library/react"

import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import { dashboardMock } from "@/lib/mock-data"

describe("SourceDetailPanel", () => {
  it("renders selected source details, metrics, and tabs without dead actions", () => {
    render(<SourceDetailPanel source={dashboardMock.sources[0]} open onOpenChange={() => undefined} />)

    expect(screen.getByRole("region", { name: /source details/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "TechCrunch" })).toBeInTheDocument()
    expect(screen.getAllByText("Healthy")).toHaveLength(2)
    expect(screen.getByText("Items (24h)")).toBeInTheDocument()
    expect(screen.getByText("8,612")).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Settings" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "History" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Logs" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /https:\/\/techcrunch.com\/feed/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /edit source/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /disable source/i })).not.toBeInTheDocument()
  })

  it("renders degraded source status intentionally", () => {
    render(<SourceDetailPanel source={{ ...dashboardMock.sources[0], status: "degraded" }} open onOpenChange={() => undefined} />)

    expect(screen.getAllByText("Degraded")).toHaveLength(2)
  })
})
