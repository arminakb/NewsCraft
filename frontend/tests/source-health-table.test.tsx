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
    expect(screen.getByRole("tab", { name: /all 53/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /rss 50/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /telegram 3/i })).toBeInTheDocument()
    expect(screen.getAllByText("Healthy")).toHaveLength(3)
    expect(screen.getByText("Degraded")).toBeInTheDocument()
    expect(screen.getByText("Broken")).toBeInTheDocument()
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
        counts={{ all: 5, rss: 5, telegram: 0 }}
      />
    )

    expect(screen.getByText("Healthy")).toBeInTheDocument()
    expect(screen.getByText("Degraded")).toBeInTheDocument()
    expect(screen.getByText("Broken")).toBeInTheDocument()
    expect(screen.getByText("Disabled")).toBeInTheDocument()
    expect(screen.getByText("Unknown")).toBeInTheDocument()
    expect(screen.getByText("Showing 5 of 5")).toBeInTheDocument()
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
