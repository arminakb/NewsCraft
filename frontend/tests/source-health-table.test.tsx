import { fireEvent, render, screen, within } from "@testing-library/react"

import { SourceHealthTable } from "@/components/dashboard/source-health-table"
import { dashboardMock } from "@/tests/fixtures/dashboard-mock"

describe("SourceHealthTable", () => {
  it("renders source rows, status badges, and platform tabs", () => {
    render(
      <SourceHealthTable
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    expect(screen.getAllByRole("row")).toHaveLength(3)
    expect(screen.getByRole("tab", { name: /all 2/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /rss 1/i })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /telegram 1/i })).toBeInTheDocument()
    expect(screen.getByText("Healthy")).toBeInTheDocument()
    expect(screen.getByText("Degraded")).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Items" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: /news|new/i })).not.toBeInTheDocument()
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

  it("switches between RSS and Telegram sources without a render loop", () => {
    render(
      <SourceHealthTable
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("tab", { name: /rss 1/i }))
    expect(screen.getByRole("row", { name: /techcrunch/i })).toBeInTheDocument()
    expect(screen.queryByRole("row", { name: /dw persian/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("tab", { name: /telegram 1/i }))
    expect(screen.getByRole("row", { name: /dw persian/i })).toBeInTheDocument()
    expect(screen.queryByRole("row", { name: /techcrunch/i })).not.toBeInTheDocument()
  })

  it("requests confirmation before deleting a source", () => {
    const onDeleteSource = vi.fn()

    render(
      <SourceHealthTable
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onDeleteSource={onDeleteSource}
        onSelectSource={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: /delete techcrunch/i }))

    expect(onDeleteSource).toHaveBeenCalledWith(dashboardMock.sources[0])
  })

  it("checks one source from its interactive status control", () => {
    const onCheckSource = vi.fn()

    render(
      <SourceHealthTable
        onCheckSource={onCheckSource}
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: /check techcrunch health, currently healthy/i }))

    expect(onCheckSource).toHaveBeenCalledWith(dashboardMock.sources[0].id)
  })

  it("disables duplicate row checks and exposes check metadata", () => {
    render(
      <SourceHealthTable
        checkingSourceIds={new Set([dashboardMock.sources[0].id])}
        onCheckSource={() => undefined}
        sources={[{
          ...dashboardMock.sources[0],
          lastCheckedAt: "2026-07-27T08:30:00Z",
          failureReason: "Source returned HTTP 503.",
        }]}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    expect(screen.getByRole("button", { name: /checking techcrunch health/i })).toBeDisabled()
    expect(screen.getByText(/last checked/i)).toBeInTheDocument()
    expect(screen.getByText(/source returned http 503/i)).toBeInTheDocument()
  })

  it("runs a bounded bulk check from the Source health button", () => {
    const onCheckAll = vi.fn()

    const { rerender } = render(
      <SourceHealthTable
        onCheckAll={onCheckAll}
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: /check all source health/i }))
    expect(onCheckAll).toHaveBeenCalledOnce()

    rerender(
      <SourceHealthTable
        bulkChecking
        onCheckAll={onCheckAll}
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )
    const checkAll = screen.getByRole("button", { name: /checking all source health/i })
    expect(checkAll).toBeDisabled()
  })

  it("does not render the unused select-source chevron action", () => {
    render(
      <SourceHealthTable
        sources={dashboardMock.sources}
        selectedSourceId={dashboardMock.sources[0].id}
        onSelectSource={() => undefined}
      />
    )

    expect(screen.queryByRole("button", { name: /select techcrunch/i })).not.toBeInTheDocument()
  })
})
