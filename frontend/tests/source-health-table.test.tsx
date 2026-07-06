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
    expect(screen.getByText("Partial")).toBeInTheDocument()
    expect(screen.getByText("Failed")).toBeInTheDocument()
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
