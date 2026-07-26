import { render, screen } from "@testing-library/react"

import { SourceDetailPanel } from "@/components/dashboard/source-detail-panel"
import { dashboardMock } from "@/tests/fixtures/dashboard-mock"

describe("SourceDetailPanel", () => {
  it("renders selected source details and real fetch interval without fake tabs", () => {
    render(<SourceDetailPanel source={dashboardMock.sources[0]} open onOpenChange={() => undefined} />)

    expect(screen.getByRole("region", { name: /source details/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "TechCrunch" })).toBeInTheDocument()
    expect(screen.getAllByText("Healthy")).toHaveLength(2)
    expect(screen.getByText("Items (24h)")).toBeInTheDocument()
    expect(screen.getByText("8,612")).toBeInTheDocument()
    expect(screen.getByText("Fetch interval")).toBeInTheDocument()
    expect(screen.getByText("Every 30 minutes")).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Settings" })).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "History" })).not.toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Logs" })).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: /https:\/\/techcrunch.com\/feed/i })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /edit source/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /disable source/i })).not.toBeInTheDocument()
  })

  it("renders degraded source status intentionally", () => {
    render(<SourceDetailPanel source={{ ...dashboardMock.sources[0], status: "degraded" }} open onOpenChange={() => undefined} />)

    expect(screen.getAllByText("Degraded")).toHaveLength(2)
  })

  it("renders an unknown platform as an unknown source", () => {
    render(
      <SourceDetailPanel
        source={{ ...dashboardMock.sources[0], platform: "unknown" }}
        open
        onOpenChange={() => undefined}
      />
    )

    expect(screen.getByText(/Unknown source - https:\/\/techcrunch.com\/feed\//)).toBeInTheDocument()
    expect(screen.getByText("Source URL")).toBeInTheDocument()
    expect(screen.queryByText("Feed URL")).not.toBeInTheDocument()
  })
})
