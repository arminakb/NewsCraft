import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import {
  activatePromptVersion,
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
import { ApiError } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

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
  output_language: "fa",
  tone: "neutral",
  editorial_rules: ["Use verified evidence"],
  attribution_rules: {},
  default_hashtags: ["#news"],
  platform_preferences: {},
  is_default: true,
}

const template = {
  id: "22222222-2222-4222-8222-222222222222",
  purposeKey: "telegram_rewrite",
  name: "Telegram rewrite",
  description: "Immutable newsroom prompt",
}

const promptVersion = {
  id: "33333333-3333-4333-8333-333333333333",
  prompt_template_id: template.id,
  version: 4,
  system_template: "Use evidence only",
  user_template: "{source_text}",
  output_schema_version: "telegram_rewrite.v1",
  output_schema: {},
  checksum_sha256: "a".repeat(64),
  is_active: true,
  activated_at: "2026-07-20T08:00:00Z",
  activated_by_type: "human_admin",
  activated_by_id: "operator",
  activation_reason: "Approved newsroom baseline",
  created_at: "2026-07-20T08:00:00Z",
}

const provider = {
  id: "44444444-4444-4444-8444-444444444444",
  name: "Newsroom model",
  protocol: "openai_compatible" as const,
  base_url: "https://llm.example/v1",
  default_model: "openai/gpt-5-mini",
  enabled: true,
  configured: true,
  settings: {
    timeout_seconds: 60,
    max_input_tokens: 60_000,
    max_output_tokens: 12_000,
    pricing: { input_usd_per_million: "0", output_usd_per_million: "0" },
    attribution_headers: { http_referer: null, app_title: "NewsCraft" },
  },
  health_status: "healthy" as const,
  generation_capability: "ready" as const,
  research_capability: "unavailable" as const,
  generation_ready: true,
  research_ready: false,
  failure_code: "research_budget_missing",
  last_checked_at: "2026-07-23T08:00:00Z",
  ownership: "operator_managed" as const,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const proxy = {
  id: "55555555-5555-4555-8555-555555555555",
  name: "Publishing proxy",
  proxy_type: "socks5" as const,
  host: "proxy.example",
  port: 1080,
  enabled: true,
  credentials_configured: true,
  reachability_status: "healthy",
  failure_code: null,
  last_checked_at: "2026-07-23T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const destination = {
  id: "66666666-6666-4666-8666-666666666666",
  name: "Main channel",
  target_ref: "@newscraft",
  canonical_target: "@newscraft",
  target_type: "username" as const,
  enabled: true,
  health_status: "healthy",
  configured: true,
  proxy_profile_id: proxy.id,
  connection_route: "Publishing proxy",
  proxy_health_status: "healthy",
  telegram_health_status: "healthy",
  bot_health_status: "authenticated",
  target_health_status: "resolved",
  administrator_status: "administrator",
  failure_code: null,
  verified_bot_id: 42,
  verified_bot_username: "newscraft_bot",
  verified_chat_id: -10042,
  verified_chat_title: "NewsCraft",
  verified_chat_type: "channel",
  last_checked_at: "2026-07-23T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const connection = {
  id: "77777777-7777-4777-8777-777777777777",
  device_name: "Editorial workstation",
  scopes: ["settings:read", "providers:read"],
  status: "green" as const,
  connection_state: "active" as const,
  failure_code: null,
  expires_at: "2026-08-23T08:00:00Z",
  last_heartbeat_at: "2026-07-24T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T08:00:00Z",
  credential_fingerprint: "sha256:test",
  revoked_at: null,
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
        connection_id: connection.id,
        action: "heartbeat",
        outcome: "success",
        reason_code: null,
        created_at: "2026-07-24T08:00:00Z",
      },
    ])
  })

  it("renders five coherent management sections and safe readiness summaries", async () => {
    renderSettings()

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Setup checklist" })).toBeInTheDocument()
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

  it("keeps non-Codex settings available when Codex requires authentication", async () => {
    const authenticationRequired = new ApiError(
      "Unauthorized",
      401,
      JSON.stringify({ detail: { code: "authentication_required" } })
    )
    vi.mocked(getCodexConnections).mockRejectedValue(authenticationRequired)
    vi.mocked(getCodexActivity).mockRejectedValue(authenticationRequired)

    renderSettings()

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Settings unavailable" })).not.toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "LLM providers" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Telegram destinations" })).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("authentication required")
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
      device_name: "Review laptop",
      scopes: ["settings:read"],
      status: "pending",
      expires_at: "2026-07-24T08:05:00Z",
      pairing_code: "one-time-code",
      local_command: "newscraft pair one-time-code",
      created_at: "2026-07-24T08:00:00Z",
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
    vi.mocked(activatePromptVersion).mockResolvedValue({ ...promptVersion, is_active: true })
    renderSettings()

    const purpose = await screen.findByRole("heading", { name: "Telegram Automation Rewrite" })
    const article = purpose.closest("article")
    expect(article).not.toBeNull()
    fireEvent.click(within(article!).getByRole("button", { name: "Manage" }))
    const userTemplate = within(article!).getByLabelText(/^User template/)
    expect(userTemplate).toHaveAttribute("dir", "auto")
    fireEvent.click(within(article!).getByText("Inspect raw template"))
    expect(within(article!).getByText(/Use evidence only/, { selector: "pre" })).toHaveAttribute("dir", "auto")
    expect(within(article!).getByRole("button", { name: "Review activation" })).toBeDisabled()
  })

  it("edits complete editorial policy, validates JSON, and refreshes every profile selector", async () => {
    vi.mocked(updateBrandProfile).mockResolvedValue({
      ...profile,
      tone: "analytical",
      attribution_rules: { preserveSources: true },
      platform_preferences: { telegram: { direction: "rtl" } },
    })
    const { queryClient } = renderSettings()
    queryClient.setQueryData(queryKeys.editorialBrandOptions, [{ id: profile.id, name: profile.name }])

    const profileHeading = await screen.findByRole("heading", { name: profile.name })
    fireEvent.click(within(profileHeading.closest("article")!).getByRole("button", { name: "Edit" }))
    const dialog = screen.getByRole("dialog", { name: `Edit ${profile.name}` })
    fireEvent.change(within(dialog).getByLabelText(/Editorial tone/), { target: { value: "analytical" } })
    const attribution = within(dialog).getByLabelText(/Attribution policy/)
    fireEvent.change(attribution, { target: { value: "[" } })
    fireEvent.blur(attribution)
    expect(within(dialog).getByRole("alert")).toHaveTextContent("valid JSON")
    expect(within(dialog).getByRole("button", { name: "Save profile" })).toBeDisabled()

    fireEvent.change(attribution, { target: { value: '{"preserveSources":true}' } })
    fireEvent.change(within(dialog).getByLabelText(/Per-platform preferences/), {
      target: { value: '{"telegram":{"direction":"rtl"}}' },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Save profile" }))

    await waitFor(() => expect(updateBrandProfile).toHaveBeenCalledWith(
      profile.id,
      expect.objectContaining({
        tone: "analytical",
        attribution_rules: { preserveSources: true },
        platform_preferences: { telegram: { direction: "rtl" } },
        is_default: true,
      }),
    ))
    expect(queryClient.getQueryState(queryKeys.editorialBrandOptions)?.isInvalidated).toBe(true)
    expect(screen.getByText(/existing revisions remain unchanged/i)).toBeInTheDocument()
  })

  it("protects, resets, and cancels unsaved editorial profile changes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    renderSettings()

    const profileHeading = await screen.findByRole("heading", { name: profile.name })
    fireEvent.click(within(profileHeading.closest("article")!).getByRole("button", { name: "Edit" }))
    const dialog = screen.getByRole("dialog", { name: `Edit ${profile.name}` })
    const tone = within(dialog).getByLabelText(/Editorial tone/)
    fireEvent.change(tone, { target: { value: "direct" } })
    expect(within(dialog).getByText("Unsaved changes")).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    expect(confirm).toHaveBeenCalledWith("Discard unsaved settings changes?")
    expect(dialog).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("button", { name: "Reset" }))
    expect(tone).toHaveValue("neutral")
    expect(within(dialog).getByText("No unsaved changes")).toBeInTheDocument()

    fireEvent.change(tone, { target: { value: "analytical" } })
    confirm.mockReturnValue(true)
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    expect(screen.queryByRole("dialog", { name: `Edit ${profile.name}` })).not.toBeInTheDocument()
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
