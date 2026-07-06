import { render, screen } from "@testing-library/react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { QueryProvider } from "@/components/providers/query-provider"
import { dashboardMock } from "@/lib/mock-data"

describe("DashboardShell", () => {
  it("renders the operational dashboard frame", () => {
    render(
      <QueryProvider>
        <DashboardShell initialData={dashboardMock} />
      </QueryProvider>
    )

    expect(screen.getByRole("navigation", { name: /dashboard navigation/i })).toBeInTheDocument()
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument()
    expect(screen.getByText("Proxy")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /run ingest/i })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: /source details/i })).toBeInTheDocument()
  })
})
