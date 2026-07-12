import { fireEvent, render, screen, within } from "@testing-library/react"

import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import { dashboardMock } from "@/lib/mock-data"

describe("SourceHealthTable", () => {
  it("renders source rows, status badges, and platform tabs", () => {
    render(
      <SourceHealthTable
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    expect(screen.getAllByRole("row")).toHaveLength(6)
    expect(screen.getByRole("tab", { name: /all 5/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /rss 3/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /telegram 2/i })).toBeInTheDocument()
    expect(screen.getAllByText("Healthy")).toHaveLength(3)
    expect(screen.getByText("Degraded")).toBeInTheDocument()
    expect(screen.getByText("Broken")).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Next run" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /source table options/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /view all sources/i })).not.toBeInTheDocument()
  })

  it("renders all backend source-health statuses", () => {
    render(
      <SourceHealthTable
        sources={[
          { ...dashboardMock.sources[0], id: "healthy", name: "Healthy source", status: "healthy" },
          { ...dashboardMock.sources[0], id: "degraded", name: "Degraded source", status: "degraded" },
          { ...dashboardMock.sources[0], id: "broken", name: "Broken source", status: "broken" },
          { ...dashboardMock.sources[0], id: "disabled", name: "Disabled source", status: "disabled" },
          { ...dashboardMock.sources[0], id: "unknown", name: "Unknown source", status: "unknown" },
        ]}
        selectedSourceId="healthy"
        onSelectSource={() => undefined}
      />
    )

    expect(screen.getByText("Healthy")).toBeInTheDocument()
    expect(screen.getByText("Degraded")).toBeInTheDocument()
    expect(screen.getByText("Broken")).toBeInTheDocument()
    expect(screen.getByText("Disabled")).toBeInTheDocument()
    expect(screen.getByText("Unknown")).toBeInTheDocument()
    expect(screen.getByText("Showing 5 of 5")).toBeInTheDocument()
  })

  it("derives tab and total counts from every actual source platform", () => {
    const sources = ["rss", "atom", "telegram_public", "google_news", "gdelt", "hackernews", "unknown"].map(
      (platform, index) => ({
        ...dashboardMock.sources[0],
        id: `source-${platform}`,
        name: `Source ${index}`,
        platform: platform as (typeof dashboardMock.sources)[number]["platform"],
      })
    )

    render(
      <SourceHealthTable
        sources={sources}
        selectedSourceId={sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    expect(screen.getByRole("tab", { name: /all 7/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /rss 1/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /telegram 1/i })).toBeInTheDocument()
    expect(screen.getByText("Showing 7 of 7")).toBeInTheDocument()
  })

  it("selects a source row", () => {
    const onSelectSource = vi.fn()

    render(
      <SourceHealthTable
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={onSelectSource}
      />
    )

    fireEvent.click(
      within(screen.getByRole("row", { name: /dw persian/i })).getByRole("button", {
        name: /open dw persian details/i,
      })
    )

    expect(onSelectSource).toHaveBeenCalledWith("telegram_dw_persian")
  })
})
