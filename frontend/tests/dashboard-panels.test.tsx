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
    expect(screen.queryByRole("button", { name: /view all runs/i })).not.toBeInTheDocument()
  })

  it("renders an empty state for ingestion runs", () => {
    render(<IngestionRunsPanel runs={[]} />)

    expect(screen.getByText("No ingestion runs yet")).toBeInTheDocument()
  })

  it("renders content queue metadata", () => {
    render(<ContentQueuePanel items={dashboardMock.queue} />)

    expect(screen.getByRole("region", { name: /content queue/i })).toBeInTheDocument()
    expect(screen.getByText(/NVIDIA announces new AI chip/i)).toBeInTheDocument()
    expect(screen.getAllByText("Economy").length).toBeGreaterThan(0)
    expect(screen.getAllByText("New")).toHaveLength(3)
    expect(screen.getAllByText("Queued")).toHaveLength(2)
    expect(screen.queryByRole("button", { name: /filter content queue/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /view all content items/i })).not.toBeInTheDocument()
    expect(screen.getByText("Showing 5 of 5")).toBeInTheDocument()
    expect(screen.queryByText(/1,284/)).not.toBeInTheDocument()
  })

  it("renders an empty state for content queue", () => {
    render(<ContentQueuePanel items={[]} />)

    expect(screen.getByText("No content items yet")).toBeInTheDocument()
    expect(screen.getByText("Showing 0 of 0")).toBeInTheDocument()
  })

  it("renders six media tiles with format and dimensions", () => {
    render(<MediaStrip media={dashboardMock.media} />)

    expect(screen.getByRole("region", { name: /media extraction/i })).toBeInTheDocument()
    expect(screen.getAllByTestId("media-tile")).toHaveLength(6)
    expect(screen.getByText("1280x720")).toBeInTheDocument()
    expect(screen.getByText("PNG")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /view all media/i })).not.toBeInTheDocument()
  })

  it("renders an empty state for media", () => {
    render(<MediaStrip media={[]} />)

    expect(screen.getByText("No media assets yet")).toBeInTheDocument()
  })
})
