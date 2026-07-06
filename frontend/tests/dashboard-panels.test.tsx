import { render, screen } from "@testing-library/react"

import { ContentQueuePanel } from "@/components/dashboard/content-queue-panel"
import { IngestionRunsPanel } from "@/components/dashboard/ingestion-runs-panel"
import { MediaStrip } from "@/components/dashboard/media-strip"
import { dashboardMock } from "@/lib/mock-data"

describe("dashboard operational panels", () => {
  it("renders latest ingestion runs with progress bars", () => {
    render(<IngestionRunsPanel runs={dashboardMock.runs} />)

    expect(screen.getByRole("region", { name: /ingestion runs/i })).toBeInTheDocument()
    expect(screen.getByText("Today 09:32")).toBeInTheDocument()
    expect(screen.getAllByRole("progressbar")).toHaveLength(5)
  })

  it("renders content queue metadata", () => {
    render(<ContentQueuePanel items={dashboardMock.queue} />)

    expect(screen.getByRole("region", { name: /content queue/i })).toBeInTheDocument()
    expect(screen.getByText(/NVIDIA announces new AI chip/i)).toBeInTheDocument()
    expect(screen.getAllByText("Economy").length).toBeGreaterThan(0)
    expect(screen.getAllByText("New")).toHaveLength(3)
    expect(screen.getAllByText("Queued")).toHaveLength(2)
  })

  it("renders six media tiles with format and dimensions", () => {
    render(<MediaStrip media={dashboardMock.media} />)

    expect(screen.getByRole("region", { name: /media extraction/i })).toBeInTheDocument()
    expect(screen.getAllByTestId("media-tile")).toHaveLength(6)
    expect(screen.getByText("1280x720")).toBeInTheDocument()
    expect(screen.getByText("PNG")).toBeInTheDocument()
  })
})
