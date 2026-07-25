import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"

import DiagnosticsPage from "@/app/diagnostics/page"
import { fetchOperationsDiagnostics } from "@/features/operations/api"
import { DiagnosticsDashboard } from "@/features/operations/diagnostics-dashboard"

vi.mock("@/features/operations/api", () => ({ fetchOperationsDiagnostics: vi.fn() }))

describe("DiagnosticsDashboard", () => {
  it("renders every persisted component with exact Tehran observations and never invents health", () => {
    render(
      <DiagnosticsDashboard
        snapshot={{
          generatedAt: "2026-07-11T08:05:00Z",
          globalPaused: false,
          dryRun: true,
          components: {
            scheduler: {
              status: "healthy",
              observedAt: "2026-07-11T08:04:00Z",
              lastSuccessAt: "2026-07-11T08:04:00Z",
              message: "Scheduler heartbeat is current.",
              actionUrl: null,
            },
            "worker-source-generation": {
              status: "unknown",
              observedAt: null,
              lastSuccessAt: null,
              message: "No heartbeat has been recorded.",
              actionUrl: "/diagnostics",
            },
            "worker-publishing": {
              status: "degraded",
              observedAt: "2026-07-11T08:00:00Z",
              lastSuccessAt: null,
              message: "Heartbeat is older than the healthy threshold.",
              actionUrl: "/jobs?status=running",
            },
            "worker-preview-eu": {
              status: "down",
              observedAt: "2026-07-11T07:45:00Z",
              lastSuccessAt: "2026-07-11T07:30:00Z",
              message: "Preview worker has stopped reporting.",
              actionUrl: null,
            },
          },
          queueCounts: { queued: 4, running: 1, failed: 2 },
          attention: [],
          outboundProxy: {
            mode: "direct",
            scheme: null,
            bypassRuleCount: 0,
            lastConnectivityStatus: "not_checked",
            configurationErrorCode: null,
          },
        }}
      />,
    )

    expect(screen.getByText("Source/generation worker status unknown")).toBeInTheDocument()
    expect(screen.getByText("Publishing worker last observed Jul 11, 2026, 11:30 AM")).toBeInTheDocument()
    expect(screen.getByText("worker-preview-eu")).toBeInTheDocument()
    expect(screen.getByText("Last successful Jul 11, 2026, 11:00 AM")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open Publishing worker action" })).toHaveAttribute(
      "href",
      "/jobs?status=running",
    )
    expect(screen.getByText("Dry run enabled")).toBeInTheDocument()
    expect(screen.getByText("Direct · 0 bypass rules · not checked")).toBeInTheDocument()
    expect(screen.getByText("healthy", { exact: true }).closest("span")).toHaveClass("bg-emerald-100")
    expect(screen.getByText("degraded", { exact: true }).closest("span")).toHaveClass("bg-amber-100")
    expect(screen.getByText("down", { exact: true }).closest("span")).toHaveClass("bg-red-100")
    expect(screen.getByText("unknown", { exact: true }).closest("span")).toHaveClass("bg-slate-100")
  })

  it("shows persisted attention with exact time, action URL, and RTL-safe prose", () => {
    render(
      <DiagnosticsDashboard
        snapshot={{
          generatedAt: "2026-07-11T08:05:00Z",
          globalPaused: true,
          dryRun: false,
          components: {},
          queueCounts: {},
          attention: [
            {
              id: "job:11111111-1111-4111-8111-111111111111",
              severity: "error",
              kind: "generation",
              title: "تولید محتوا نیاز به بررسی دارد",
              occurredAt: "2026-07-11T08:02:00Z",
              actionUrl: "/jobs?status=needs_review",
            },
          ],
          outboundProxy: {
            mode: "proxy",
            scheme: "socks5h",
            bypassRuleCount: 2,
            lastConnectivityStatus: "failed",
            configurationErrorCode: "proxy_connectivity_failed",
          },
        }}
      />,
    )

    const title = screen.getByText("تولید محتوا نیاز به بررسی دارد")
    expect(title.closest("[dir]")).toHaveAttribute("dir", "auto")
    expect(screen.getByText("Jul 11, 2026, 11:32 AM")).toBeInTheDocument()
    expect(screen.getByText("Operations paused")).toBeInTheDocument()
    expect(screen.getByText("Configuration error: proxy_connectivity_failed")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Review تولید محتوا نیاز به بررسی دارد" })).toHaveAttribute(
      "href",
      "/jobs?status=needs_review",
    )
    expect(screen.getByText("error", { exact: true }).closest("span")).toHaveClass("bg-red-100", "text-red-900")
    expect(title.closest("li")?.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
  })

  it("preserves API error direction on the diagnostics route", async () => {
    vi.mocked(fetchOperationsDiagnostics).mockRejectedValueOnce(new Error("سامانه در دسترس نیست"))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <DiagnosticsPage />
      </QueryClientProvider>,
    )

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("سامانه در دسترس نیست")
    expect(alert).toHaveAttribute("dir", "auto")
  })
})
