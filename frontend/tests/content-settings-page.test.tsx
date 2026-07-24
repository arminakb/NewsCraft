import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import {
  activatePromptVersion,
  createBrandProfile,
  createPromptVersion,
  getBrandProfiles,
  getPromptTemplates,
  getPromptVersions,
  updateBrandProfile,
} from "@/features/automations/telegram-api"
import {
  createCodexPairingSession,
  createLLMProvider,
  createTelegramDestination,
  getCodexActivity,
  getCodexConnections,
  getLLMProviders,
  getTelegramDestinations,
  getTelegramProxies,
} from "@/features/settings/content-settings-api"
import { ContentSettingsPage } from "@/features/settings/content-settings-page"

vi.mock("@/features/automations/telegram-api", () => ({
  activatePromptVersion: vi.fn(),
  createBrandProfile: vi.fn(),
  createPromptVersion: vi.fn(),
  getBrandProfiles: vi.fn(),
  getPromptTemplates: vi.fn(),
  getPromptVersions: vi.fn(),
  updateBrandProfile: vi.fn(),
}))

vi.mock("@/features/settings/content-settings-api", () => ({
  createCodexPairingSession: vi.fn(),
  createLLMProvider: vi.fn(),
  createTelegramDestination: vi.fn(),
  createTelegramProxy: vi.fn(),
  deleteLLMProvider: vi.fn(),
  deleteTelegramDestination: vi.fn(),
  deleteTelegramProxy: vi.fn(),
  getCodexActivity: vi.fn(),
  getCodexConnections: vi.fn(),
  getLLMProviderDependencies: vi.fn(),
  getLLMProviders: vi.fn(),
  getTelegramDestinationDependencies: vi.fn(),
  getTelegramDestinations: vi.fn(),
  getTelegramProxies: vi.fn(),
  getTelegramProxyDependencies: vi.fn(),
  recheckTelegramDestination: vi.fn(),
  recheckTelegramProxy: vi.fn(),
  revokeCodexConnection: vi.fn(),
  rotateCodexConnection: vi.fn(),
  rotateLLMProviderKey: vi.fn(),
  rotateTelegramToken: vi.fn(),
  setLLMProviderEnabled: vi.fn(),
  setTelegramDestinationEnabled: vi.fn(),
  setTelegramProxyEnabled: vi.fn(),
  testLLMProvider: vi.fn(),
  updateLLMProvider: vi.fn(),
  updateTelegramDestination: vi.fn(),
  updateTelegramProxy: vi.fn(),
}))

const profile = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "News desk",
  outputLanguage: "fa",
  tone: "neutral",
  editorialRules: ["Use verified evidence"],
  attributionRules: {},
  defaultHashtags: ["#news"],
  platformPreferences: {},
  isDefault: true,
}

const template = {
  id: "22222222-2222-4222-8222-222222222222",
  purposeKey: "telegram_rewrite",
  name: "Telegram rewrite",
  description: "Immutable newsroom prompt",
}

const promptVersion = {
  id: "33333333-3333-4333-8333-333333333333",
  promptTemplateId: template.id,
  version: 4,
  systemTemplate: "Use evidence only",
  userTemplate: "{source_text}",
  outputSchemaVersion: "telegram_rewrite.v1",
  outputSchema: {},
  checksumSha256: "a".repeat(64),
  isActive: true,
  createdAt: "2026-07-20T08:00:00Z",
}

const provider = {
  id: "44444444-4444-4444-8444-444444444444",
  name: "Newsroom model",
  protocol: "openai_compatible" as const,
  baseUrl: "https://llm.example/v1",
  defaultModel: "openai/gpt-5-mini",
  enabled: true,
  configured: true,
  settings: {
    timeoutSeconds: 60,
    maxInputTokens: 60_000,
    maxOutputTokens: 12_000,
    researchBudgets: {},
    pricing: { inputUsdPerMillion: 0, outputUsdPerMillion: 0 },
    attributionHeaders: { httpReferer: null, appTitle: "NewsCraft" },
  },
  healthStatus: "healthy" as const,
  generationCapability: "ready" as const,
  researchCapability: "unavailable" as const,
  generationReady: true,
  researchReady: false,
  failureCode: "research_budget_missing",
  lastCheckedAt: "2026-07-23T08:00:00Z",
  ownership: "operator_managed" as const,
}

const proxy = {
  id: "55555555-5555-4555-8555-555555555555",
  name: "Publishing proxy",
  proxyType: "socks5" as const,
  host: "proxy.example",
  port: 1080,
  enabled: true,
  credentialsConfigured: true,
  reachabilityStatus: "healthy",
  failureCode: null,
  lastCheckedAt: "2026-07-23T08:00:00Z",
}

const destination = {
  id: "66666666-6666-4666-8666-666666666666",
  name: "Main channel",
  targetRef: "@newscraft",
  canonicalTarget: "@newscraft",
  targetType: "username" as const,
  enabled: true,
  healthStatus: "healthy",
  configured: true,
  proxyProfileId: proxy.id,
  connectionRoute: "Publishing proxy",
  proxyHealthStatus: "healthy",
  telegramHealthStatus: "healthy",
  botHealthStatus: "authenticated",
  targetHealthStatus: "resolved",
  administratorStatus: "administrator",
  failureCode: null,
  verifiedBotUsername: "newscraft_bot",
  verifiedChatTitle: "NewsCraft",
  lastCheckedAt: "2026-07-23T08:00:00Z",
}

const connection = {
  id: "77777777-7777-4777-8777-777777777777",
  deviceName: "Editorial workstation",
  scopes: ["settings:read", "providers:read"],
  status: "green" as const,
  connectionState: "active" as const,
  failureCode: null,
  expiresAt: "2026-08-23T08:00:00Z",
  lastHeartbeatAt: "2026-07-24T08:00:00Z",
  lastRotatedAt: null,
}

describe("ContentSettingsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getBrandProfiles).mockResolvedValue([profile])
    vi.mocked(getPromptTemplates).mockResolvedValue([template])
    vi.mocked(getPromptVersions).mockResolvedValue([promptVersion])
    vi.mocked(getLLMProviders).mockResolvedValue([provider])
    vi.mocked(getTelegramProxies).mockResolvedValue([proxy])
    vi.mocked(getTelegramDestinations).mockResolvedValue([destination])
    vi.mocked(getCodexConnections).mockResolvedValue([connection])
    vi.mocked(getCodexActivity).mockResolvedValue([
      {
        id: "88888888-8888-4888-8888-888888888888",
        connectionId: connection.id,
        action: "heartbeat",
        outcome: "success",
        reasonCode: null,
        createdAt: "2026-07-24T08:00:00Z",
      },
    ])
  })

  it("renders five coherent management sections and safe readiness summaries", async () => {
    renderSettings()

    expect(await screen.findByRole("heading", { name: "Content settings" })).toBeInTheDocument()
    for (const heading of [
      "Editorial profiles",
      "LLM providers",
      "Codex connection",
      "Telegram destinations",
      "Prompt governance",
    ]) expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument()

    expect(screen.getByText("1 enabled")).toBeInTheDocument()
    expect(screen.getByText("1/1 healthy")).toBeInTheDocument()
    expect(screen.getByText("1 connected")).toBeInTheDocument()
    expect(screen.getByText("Generation: ready")).toBeInTheDocument()
    expect(screen.getByText("Research: unavailable")).toBeInTheDocument()
    expect(screen.getByText("research budget missing")).toBeInTheDocument()
    expect(screen.getByText(/@newscraft_bot/)).toBeInTheDocument()
    expect(screen.queryByText(/bot token/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/api key/i)).not.toHaveTextContent("sk-")
  })

  it("creates a generic provider through one write-only form and resets dirty values", async () => {
    vi.mocked(createLLMProvider).mockResolvedValue({ ...provider, id: "99999999-9999-4999-8999-999999999999" })
    renderSettings()

    fireEvent.click(await screen.findByRole("button", { name: "Add provider" }))
    const dialog = screen.getByRole("dialog", { name: "Add LLM provider" })
    const submit = within(dialog).getByRole("button", { name: "Add provider" })
    expect(submit).toBeDisabled()

    fireEvent.change(within(dialog).getByLabelText(/Connection name/), { target: { value: "Custom model" } })
    fireEvent.change(within(dialog).getByLabelText(/Model name/), { target: { value: "vendor/model" } })
    fireEvent.change(within(dialog).getByLabelText(/Base URL/), { target: { value: "http://unsafe.example/v1" } })
    fireEvent.blur(within(dialog).getByLabelText(/Base URL/))
    expect(within(dialog).getByRole("alert")).toHaveTextContent("HTTPS")
    fireEvent.change(within(dialog).getByLabelText(/Base URL/), { target: { value: "https://safe.example/v1" } })
    fireEvent.change(within(dialog).getByLabelText(/API key/), { target: { value: "write-only-value" } })
    fireEvent.click(submit)

    await waitFor(() => expect(createLLMProvider).toHaveBeenCalledWith(expect.objectContaining({
      name: "Custom model",
      baseUrl: "https://safe.example/v1",
      defaultModel: "vendor/model",
      apiKey: "write-only-value",
    })))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add LLM provider" })).not.toBeInTheDocument())
    expect(screen.queryByDisplayValue("write-only-value")).not.toBeInTheDocument()
  })

  it("creates a Telegram destination with a reusable route and no auto-publish permission", async () => {
    vi.mocked(createTelegramDestination).mockResolvedValue({
      destination: { ...destination, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "Backup" },
      jobId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    })
    renderSettings()

    fireEvent.click(await screen.findByRole("button", { name: "Add destination" }))
    const dialog = screen.getByRole("dialog", { name: "Add Telegram destination" })
    fireEvent.change(within(dialog).getByLabelText(/Destination name/), { target: { value: "Backup" } })
    fireEvent.change(within(dialog).getByLabelText(/Channel or group identifier/), { target: { value: "@backup" } })
    fireEvent.change(within(dialog).getByLabelText(/Bot token/), { target: { value: "telegram-write-only" } })
    fireEvent.change(within(dialog).getByLabelText("Connection route"), { target: { value: proxy.id } })
    expect(within(dialog).queryByLabelText(/auto.?publish/i)).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "Add destination" }))

    await waitFor(() => expect(createTelegramDestination).toHaveBeenCalledWith({
      name: "Backup",
      target: "@backup",
      botToken: "telegram-write-only",
      proxyProfileId: proxy.id,
    }))
    expect(screen.queryByDisplayValue("telegram-write-only")).not.toBeInTheDocument()
  })

  it("pairs Codex with explicit read scopes and shows one-time output", async () => {
    vi.mocked(createCodexPairingSession).mockResolvedValue({
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      deviceName: "Review laptop",
      scopes: ["settings:read"],
      status: "pending",
      expiresAt: "2026-07-24T08:05:00Z",
      pairingCode: "one-time-code",
      localCommand: "newscraft pair one-time-code",
    })
    renderSettings()

    fireEvent.click(await screen.findByRole("button", { name: "Pair Codex" }))
    const dialog = screen.getByRole("dialog", { name: "Pair Codex" })
    fireEvent.change(within(dialog).getByLabelText(/Agent or device name/), { target: { value: "Review laptop" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Create pairing code" }))

    await waitFor(() => expect(createCodexPairingSession).toHaveBeenCalledWith(
      "Review laptop",
      expect.arrayContaining(["settings:read", "providers:read"])
    ))
    const output = await screen.findByRole("dialog", { name: "Pair Review laptop" })
    expect(within(output).getByDisplayValue("one-time-code")).toBeInTheDocument()
    expect(within(output).getByText(/Shown once/)).toBeInTheDocument()
  })

  it("keeps raw prompt text directional and activation guarded", async () => {
    vi.mocked(activatePromptVersion).mockResolvedValue({ ...promptVersion, isActive: true })
    renderSettings()

    const purpose = await screen.findByRole("heading", { name: "Telegram Automation Rewrite" })
    const article = purpose.closest("article")
    expect(article).not.toBeNull()
    fireEvent.click(within(article!).getByRole("button", { name: "Manage" }))
    const userTemplate = within(article!).getByLabelText("User template")
    expect(userTemplate).toHaveAttribute("dir", "auto")
    fireEvent.click(within(article!).getByText("Inspect raw template"))
    expect(within(article!).getByText(/Use evidence only/)).toHaveAttribute("dir", "auto")
    expect(within(article!).getByRole("button", { name: "Activate" })).toBeDisabled()
  })
})

function renderSettings() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <NoticeProvider>
          <ContentSettingsPage />
        </NoticeProvider>
      </QueryClientProvider>
    ),
  }
}
