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
          generated_at: "2026-07-11T08:05:00Z",
          global_paused: false,
          dry_run: true,
          components: {
            scheduler: {
              status: "healthy",
              observed_at: "2026-07-11T08:04:00Z",
              last_success_at: "2026-07-11T08:04:00Z",
              message: "Scheduler heartbeat is current.",
              action_url: null,
            },
            "worker-source-generation": {
              status: "unknown",
              observed_at: null,
              last_success_at: null,
              message: "No heartbeat has been recorded.",
              action_url: "/diagnostics",
            },
            "worker-publishing": {
              status: "degraded",
              observed_at: "2026-07-11T08:00:00Z",
              last_success_at: null,
              message: "Heartbeat is older than the healthy threshold.",
              action_url: "/jobs?status=running",
            },
            "worker-preview-eu": {
              status: "down",
              observed_at: "2026-07-11T07:45:00Z",
              last_success_at: "2026-07-11T07:30:00Z",
              message: "Preview worker has stopped reporting.",
              action_url: null,
            },
          },
          queue_counts: { queued: 4, running: 1, failed: 2 },
          attention: [],
          outbound_proxy: {
            mode: "direct",
            scheme: null,
            bypass_rule_count: 0,
            last_connectivity_status: "not_checked",
            configuration_error_code: null,
          },
        }}
      />,
    )

    expect(screen.getByText("Source/generation worker status unknown")).toBeInTheDocument()
    expect(screen.getByText("Publishing worker last observed Jul 11, 2026, 11:30 AM")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "worker-preview-eu" })).toBeInTheDocument()
    expect(screen.getByText("Last successful Jul 11, 2026, 11:00 AM")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open Publishing worker action" })).toHaveAttribute(
      "href",
      "/jobs?status=running",
    )
    expect(screen.getByText("Dry run enabled")).toBeInTheDocument()
    expect(screen.getByText("Direct · 0 bypass rules · not checked")).toBeInTheDocument()
    expect(screen.getByText("healthy", { exact: true }).closest("span")).toHaveClass("bg-[var(--success-surface)]", "text-success")
    expect(screen.getByText("degraded", { exact: true }).closest("span")).toHaveClass("bg-[var(--warning-surface)]", "text-warning")
    expect(screen.getByText("down", { exact: true }).closest("span")).toHaveClass("bg-[var(--error-surface)]", "text-destructive")
    expect(screen.getByText("unknown", { exact: true }).closest("span")).toHaveClass("bg-muted", "text-muted-foreground")
  })

  it("shows persisted attention with exact time, action URL, and RTL-safe prose", () => {
    render(
      <DiagnosticsDashboard
        snapshot={{
          generated_at: "2026-07-11T08:05:00Z",
          global_paused: true,
          dry_run: false,
          components: {},
          queue_counts: {},
          attention: [
            {
              id: "job:11111111-1111-4111-8111-111111111111",
              severity: "error",
              kind: "generation",
              title: "تولید محتوا نیاز به بررسی دارد",
              occurred_at: "2026-07-11T08:02:00Z",
              action_url: "/jobs?status=needs_review",
            },
          ],
          outbound_proxy: {
            mode: "proxy",
            scheme: "socks5h",
            bypass_rule_count: 2,
            last_connectivity_status: "failed",
            configuration_error_code: "proxy_connectivity_failed",
          },
        }}
      />,
    )

    const title = screen.getByText("تولید محتوا نیاز به بررسی دارد")
    expect(title.closest("[dir]")).toHaveAttribute("dir", "auto")
    expect(screen.getByText("Jul 11, 2026, 11:32 AM")).toBeInTheDocument()
    expect(screen.getByText("Operations paused")).toBeInTheDocument()
    expect(screen.getByText("Configuration error: proxy connectivity failed")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open repair تولید محتوا نیاز به بررسی دارد" })).toHaveAttribute(
      "href",
      "/jobs?status=needs_review",
    )
    expect(screen.getByText("error", { exact: true }).closest("span")).toHaveClass("bg-[var(--error-surface)]", "text-destructive")
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
