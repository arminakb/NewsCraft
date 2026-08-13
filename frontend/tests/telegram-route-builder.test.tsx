import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import {
  createTelegramRoute,
  createTelegramSource,
  getTelegramAutomationOptions,
} from "@/features/automations/telegram-api"
import { RouteBuilder } from "@/features/automations/route-builder"
import type { TelegramAutomationOptions } from "@/features/automations/telegram-types"

vi.mock("@/features/automations/telegram-api", () => ({
  createTelegramRoute: vi.fn(),
  createTelegramSource: vi.fn(),
  getTelegramAutomationOptions: vi.fn(),
}))

const options: TelegramAutomationOptions = {
  sources: [],
  destinations: [{ id: "destination-1", name: "Main newsroom", healthStatus: "healthy", capabilityState: availableState() }],
  brandProfiles: [{ id: "brand-1", name: "Persian newsroom" }],
  promptTemplateVersions: [{ id: "prompt-1", version: 3, isActive: true, checksumSha256: "a".repeat(64) }],
  aiProviderProfiles: [{ id: "provider-1", name: "Editorial AI", providerType: "openrouter", defaultModel: "model", configured: true, capabilities: { generation: true, research: true }, capabilityStates: { generation: availableState(), research: availableState() } }],
}

describe("RouteBuilder", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getTelegramAutomationOptions).mockResolvedValue(options)
    vi.mocked(createTelegramSource).mockResolvedValue({ id: "source-1" } as never)
    vi.mocked(createTelegramRoute).mockResolvedValue({ id: "route-1", name: "Morning route" } as never)
  })

  it("renders safe options and conservative defaults without credential-value inputs", async () => {
    renderBuilder()

    expect(await screen.findByRole("option", { name: "Persian newsroom" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "Prompt version 3 · active" })).toBeInTheDocument()
    expect(screen.getByLabelText("Prompt update policy")).toHaveValue("pinned")
    expect(screen.getByRole("option", { name: "Editorial AI" })).toBeInTheDocument()
    expect(screen.getByLabelText("Telegram destination")).toHaveValue("destination-1")
    expect(screen.getByRole("link", { name: "Manage destinations" })).toHaveAttribute(
      "href",
      "/settings?section=telegram",
    )
    expect(screen.getByLabelText("Access mode")).toHaveValue("public_html")
    expect(screen.getByLabelText("Research mode")).toHaveValue("off")
    expect(screen.getByLabelText("Media policy")).toHaveValue("preserve")
    expect(screen.getByLabelText("Publishing policy")).toHaveValue("review_required")
    expect(screen.getByLabelText("Poll interval in seconds")).toHaveValue(300)
    expect(document.querySelector('input[type="password"]')).not.toBeInTheDocument()
    expect(screen.queryByText(/secret[_ -]?ref/i)).not.toBeInTheDocument()
  })

  it("blocks creation and links to destination management when no destination is ready", async () => {
    vi.mocked(getTelegramAutomationOptions).mockResolvedValue({ ...options, destinations: [] })
    renderBuilder()

    expect(await screen.findByRole("option", { name: "No ready destinations" })).toBeInTheDocument()
    expect(screen.getByText("Create and verify a destination before building an automation.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Manage destinations" })).toHaveAttribute(
      "href",
      "/settings?section=telegram",
    )
    expect(screen.getByRole("button", { name: "Create automation" })).toBeDisabled()
  })

  it("reveals three environment-name fields for MTProto and requires explicit auto-publish confirmation", async () => {
    renderBuilder()
    await screen.findByRole("option", { name: "Persian newsroom" })

    fireEvent.change(screen.getByLabelText("Access mode"), { target: { value: "mtproto_user" } })
    expect(screen.getAllByLabelText(/^(API ID|API hash|Session) environment variable$/)).toHaveLength(3)
    expect(screen.getByLabelText("API ID environment variable")).toHaveAttribute("pattern", "[A-Z][A-Z0-9_]{2,127}")
    expect(screen.getByLabelText("API hash environment variable")).toBeInTheDocument()
    expect(screen.getByLabelText("Session environment variable")).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("API ID environment variable"), { target: { value: "TELEGRAM_API_ID" } })
    fireEvent.change(screen.getByLabelText("API hash environment variable"), { target: { value: "TELEGRAM_API_HASH" } })
    fireEvent.change(screen.getByLabelText("Session environment variable"), { target: { value: "TELEGRAM_SESSION" } })

    fireEvent.change(screen.getByLabelText("Publishing policy"), { target: { value: "auto_publish" } })
    fireEvent.change(screen.getByLabelText("Prompt update policy"), { target: { value: "follow_active" } })
    const submit = screen.getByRole("button", { name: "Create automation" })
    expect(screen.getByRole("checkbox", { name: /confirm automatic publishing/i })).not.toBeChecked()
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByRole("checkbox", { name: /confirm automatic publishing/i }))
    expect(submit).toBeEnabled()
  })

  it("creates configuration without activating before workers observe credentials", async () => {
    const order: string[] = []
    vi.mocked(createTelegramSource).mockImplementation(async () => { order.push("source"); return { id: "source-1" } as never })
    vi.mocked(createTelegramRoute).mockImplementation(async () => { order.push("route"); return { id: "route-1" } as never })
    renderBuilder()
    await screen.findByRole("option", { name: "Persian newsroom" })

    fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Morning route" } })
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "Tehran feed" } })
    fireEvent.change(screen.getByLabelText("Source channel"), { target: { value: "tehran_feed" } })
    fireEvent.change(screen.getByLabelText("Prompt update policy"), { target: { value: "follow_active" } })
    fireEvent.click(screen.getByRole("button", { name: "Create automation" }))

    await waitFor(() => expect(order).toEqual(["source", "route"]))
    expect(createTelegramRoute).toHaveBeenCalledWith(expect.objectContaining({
      accessMode: "public_html",
      researchMode: "off",
      mediaPolicy: "preserve",
      publishingPolicy: "review_required",
      pollIntervalSeconds: 300,
      sourceId: "source-1",
      destinationId: "destination-1",
    }))
    expect(await screen.findByRole("status", { name: "Automation creation outcome" })).toHaveTextContent("owning workers report current capability status")
  })

  it("shows all research modes and submits only an available profile UUID", async () => {
    renderBuilder()
    await screen.findByRole("option", { name: "Persian newsroom" })
    expect(screen.getByRole("option", { name: "Off" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "Manual" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "Automatic if incomplete" })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Research mode"), { target: { value: "auto_if_incomplete" } })
    expect(screen.getByLabelText("Research provider")).toHaveValue("provider-1")
    fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Research route" } })
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "Research source" } })
    fillRequiredConnectionFields()
    fireEvent.click(screen.getByRole("button", { name: "Create automation" }))
    await waitFor(() => expect(createTelegramRoute).toHaveBeenCalled())
    const input = vi.mocked(createTelegramRoute).mock.calls[0][0]
    expect(input).toMatchObject({ researchMode: "auto_if_incomplete", contentFilters: { researchProviderProfileId: "provider-1" } })
    expect(JSON.stringify(input)).not.toMatch(/research_backend|openrouter|codex|fake/)
  })

  it("keeps entered values and exposes the server error", async () => {
    vi.mocked(createTelegramRoute).mockRejectedValue(new Error("Destination health check unavailable"))
    renderBuilder()
    await screen.findByRole("option", { name: "Persian newsroom" })

    fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "Keep me" } })
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "Source retained" } })
    fillRequiredConnectionFields()
    fireEvent.click(screen.getByRole("button", { name: "Create automation" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Destination health check unavailable")
    expect(screen.getByLabelText("Automation name")).toHaveValue("Keep me")
    expect(screen.getByLabelText("Source name")).toHaveValue("Source retained")
  })
})

function fillRequiredConnectionFields() {
  fireEvent.change(screen.getByLabelText("Prompt update policy"), { target: { value: "follow_active" } })
  fireEvent.change(screen.getByLabelText("Source channel"), { target: { value: "channel" } })
}

function availableState() {
  return {
    status: "available" as const,
    owner: "worker-source-generation",
    observedAt: "2026-07-18T08:00:00Z",
    expiresAt: "2026-07-18T08:02:00Z",
    failureCode: "available",
  }
}

function renderBuilder() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><RouteBuilder /></QueryClientProvider>)
}
