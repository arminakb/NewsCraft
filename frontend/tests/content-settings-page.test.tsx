import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import {
  activatePromptVersion,
  createAIProviderProfile,
  createBrandProfile,
  createPromptVersion,
  createTelegramDestination,
  getAIProviderProfiles,
  getBrandProfiles,
  getPromptTemplates,
  getPromptVersions,
  getTelegramDestinations,
  updateAIProviderProfile,
  updateBrandProfile,
} from "@/features/automations/telegram-api"
import { ContentSettingsPage } from "@/features/settings/content-settings-page"

vi.mock("@/features/automations/telegram-api", () => ({
  activatePromptVersion: vi.fn(),
  createAIProviderProfile: vi.fn(),
  createBrandProfile: vi.fn(),
  createPromptTemplate: vi.fn(),
  createPromptVersion: vi.fn(),
  createTelegramDestination: vi.fn(),
  getAIProviderProfiles: vi.fn(),
  getBrandProfiles: vi.fn(),
  getPromptTemplates: vi.fn(),
  getPromptVersions: vi.fn(),
  getTelegramDestinations: vi.fn(),
  updateAIProviderProfile: vi.fn(),
  updateBrandProfile: vi.fn(),
}))

const telegramTemplate = {
  id: "11111111-1111-4111-8111-111111111111",
  purposeKey: "telegram_rewrite",
  name: "Telegram rewrite",
  description: "Immutable newsroom prompt",
}
const activeVersion = {
  id: "22222222-2222-4222-8222-222222222222",
  promptTemplateId: telegramTemplate.id,
  version: 1,
  systemTemplate: "Write faithfully",
  userTemplate:
    "{source_text} {source_url} {source_channel} {language} {direction} {attribution_policy} {custom_footer}",
  outputSchemaVersion: "telegram_rewrite.v1",
  outputSchema: {},
  checksumSha256: "a".repeat(64),
  isActive: false,
  createdAt: "2026-07-12T08:00:00Z",
}

describe("ContentSettingsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getBrandProfiles).mockResolvedValue([
      {
        id: "33333333-3333-4333-8333-333333333333",
        name: "News desk",
        outputLanguage: "fa",
        tone: "neutral",
        editorialRules: [],
        attributionRules: {},
        defaultHashtags: [],
        platformPreferences: {},
        isDefault: true,
      },
    ])
    vi.mocked(getPromptTemplates).mockResolvedValue([telegramTemplate])
    vi.mocked(getPromptVersions).mockResolvedValue([activeVersion])
    vi.mocked(getAIProviderProfiles).mockResolvedValue([
      {
        id: "44444444-4444-4444-8444-444444444444",
        name: "OpenRouter newsroom",
        providerType: "openrouter",
        defaultModel: "openai/gpt-5-mini",
        settings: {},
        enabled: true,
        configured: false,
        capabilities: { generation: false, research: false },
        unavailabilityCodes: ["secret_unavailable"],
      },
      {
        id: "45454545-4545-4454-8454-454545454545",
        name: "Codex CLI",
        providerType: "codex",
        defaultModel: "gpt-5.4",
        settings: { timeout_seconds: 120 },
        enabled: true,
        configured: false,
        capabilities: { generation: false, research: false },
        unavailabilityCodes: ["executable_unavailable"],
      },
    ])
    vi.mocked(getTelegramDestinations).mockResolvedValue([
      {
        id: "55555555-5555-4555-8555-555555555555",
        name: "Main channel",
        targetRef: "@newscraft",
        enabled: true,
        healthStatus: "healthy",
        configured: true,
        settings: { allowAutoPublish: false },
      },
    ])
  })

  it("keeps prompt prose directional while leaving the shell as the only main landmark", async () => {
    const view = renderSettings()

    const instructions = await screen.findByLabelText("Custom instructions")
    expect(instructions).toHaveAttribute("data-testid", "direction-boundary")
    expect(instructions).toHaveAttribute("dir", "auto")
    expect(screen.getByLabelText("User template")).toHaveAttribute("dir", "auto")
    await screen.findByText("Version 1")
    fireEvent.click(screen.getByText("Inspect immutable templates"))
    expect(screen.getByText(/Write faithfully/)).toHaveAttribute("dir", "auto")
    expect(view.container.querySelector("main")).not.toBeInTheDocument()
  })

  it("creates and updates brands, then creates and confirms an immutable prompt activation", async () => {
    vi.mocked(createBrandProfile).mockResolvedValue({
      ...(await getBrandProfiles())[0],
      id: "66666666-6666-4666-8666-666666666666",
      name: "Breaking desk",
    })
    vi.mocked(updateBrandProfile).mockResolvedValue({ ...(await getBrandProfiles())[0], tone: "urgent" })
    const version2 = { ...activeVersion, id: "77777777-7777-4777-8777-777777777777", version: 2, isActive: false }
    vi.mocked(createPromptVersion).mockResolvedValue(version2)
    vi.mocked(activatePromptVersion).mockResolvedValue({ ...version2, isActive: true })
    const { queryClient } = renderSettings()
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")

    fireEvent.change(await screen.findByLabelText("New brand name"), { target: { value: "Breaking desk" } })
    fireEvent.click(screen.getByRole("button", { name: "Create brand" }))
    await waitFor(() => expect(createBrandProfile).toHaveBeenCalledWith(expect.objectContaining({ name: "Breaking desk" })))

    const brand = screen.getByRole("group", { name: "Brand News desk" })
    fireEvent.change(within(brand).getByLabelText("Tone"), { target: { value: "urgent" } })
    fireEvent.click(within(brand).getByRole("button", { name: "Save brand" }))
    await waitFor(() =>
      expect(updateBrandProfile).toHaveBeenCalledWith(
        "33333333-3333-4333-8333-333333333333",
        expect.objectContaining({ tone: "urgent" })
      )
    )

    fireEvent.change(screen.getByLabelText("Custom instructions"), { target: { value: "Use the verified evidence only" } })
    fireEvent.click(screen.getByRole("button", { name: "Create prompt version" }))
    await waitFor(() =>
      expect(createPromptVersion).toHaveBeenCalledWith(
        telegramTemplate.id,
        expect.objectContaining({
          systemTemplate: "Use the verified evidence only",
          userTemplate: expect.stringContaining("{source_text}"),
        })
      )
    )
    const body = vi.mocked(createPromptVersion).mock.calls[0][1].userTemplate
    for (const placeholder of [
      "source_text",
      "source_url",
      "source_channel",
      "language",
      "direction",
      "attribution_policy",
      "custom_footer",
    ]) expect(body).toContain(`{${placeholder}}`)

    fireEvent.change(screen.getByLabelText("User template"), { target: { value: "{source_text}" } })
    expect(screen.getByRole("alert")).toHaveTextContent("source_url")
    expect(screen.getByRole("button", { name: "Create prompt version" })).toBeDisabled()

    expect(screen.getByText("Version 1")).toBeInTheDocument()
    const activate = screen.getByRole("button", { name: "Activate version 1" })
    expect(activate).toBeDisabled()
    fireEvent.click(screen.getByRole("checkbox", { name: "Confirm prompt activation" }))
    fireEvent.click(activate)
    await waitFor(() => expect(activatePromptVersion).toHaveBeenCalledWith(activeVersion.id))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["settings", "prompt-templates", "editorial-options"] })
  })

  it("uses only environment-variable names for providers, clears them, and renders safe configuration truth", async () => {
    vi.mocked(createAIProviderProfile).mockResolvedValue({
      id: "88888888-8888-4888-8888-888888888888",
      name: "OpenRouter custom",
      providerType: "openrouter",
      defaultModel: "openai/gpt-5-mini",
      settings: {},
      enabled: true,
      configured: true,
      capabilities: { generation: true, research: true },
      unavailabilityCodes: [],
    })
    vi.mocked(updateAIProviderProfile).mockResolvedValue({
      ...(await getAIProviderProfiles())[0],
      configured: true,
    })
    renderSettings()

    const envName = await screen.findByLabelText("Provider environment variable name")
    fireEvent.change(screen.getByLabelText("Provider profile name"), { target: { value: "OpenRouter custom" } })
    fireEvent.change(envName, { target: { value: "OPENROUTER_API_KEY" } })
    fireEvent.click(screen.getByRole("button", { name: "Create OpenRouter profile" }))
    await waitFor(() =>
      expect(createAIProviderProfile).toHaveBeenCalledWith(
        expect.objectContaining({ providerType: "openrouter", secretRef: "OPENROUTER_API_KEY" })
      )
    )
    await waitFor(() => expect(envName).toHaveValue(""))

    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0)
    expect(screen.queryByText("OPENROUTER_INTERNAL_SECRET")).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/password|token/i)).not.toBeInTheDocument()

    const provider = screen.getByRole("group", { name: "Provider OpenRouter newsroom" })
    const replacementEnvironment = within(provider).getByLabelText("Replacement environment variable name")
    fireEvent.change(replacementEnvironment, { target: { value: "bad" } })
    expect(within(provider).getByRole("button", { name: "Save provider" })).toBeDisabled()
    expect(within(provider).getByRole("alert")).toHaveTextContent("3–128 characters")
    expect(updateAIProviderProfile).not.toHaveBeenCalled()
    fireEvent.change(within(provider).getByLabelText("Replacement environment variable name"), {
      target: { value: "OPENROUTER_ROTATED_KEY" },
    })
    fireEvent.click(within(provider).getByRole("button", { name: "Save provider" }))
    await waitFor(() =>
      expect(updateAIProviderProfile).toHaveBeenCalledWith(
        "44444444-4444-4444-8444-444444444444",
        expect.objectContaining({ secretRef: "OPENROUTER_ROTATED_KEY" })
      )
    )
    expect(within(provider).getByLabelText("Replacement environment variable name")).toHaveValue("")
  })

  it("shows exact Codex capability and executable truth without any secret field", async () => {
    renderSettings()
    const codex = await screen.findByRole("group", { name: "Provider Codex CLI" })
    expect(codex).toHaveTextContent("Generation unavailable")
    expect(codex).toHaveTextContent("Research unavailable")
    expect(codex).toHaveTextContent("executable unavailable")
    expect(within(codex).queryByLabelText("Replacement environment variable name")).not.toBeInTheDocument()
    expect(within(codex).getByRole("button", { name: "Save provider" })).toBeDisabled()
  })

  it("shows destination health and auto-publish configuration without exposing secret references", async () => {
    vi.mocked(createTelegramDestination).mockResolvedValue({
      destination: { ...(await getTelegramDestinations())[0] },
      job: { jobId: "99999999-9999-4999-8999-999999999999", status: "queued", deduplicated: false },
    })
    renderSettings()

    const destination = await screen.findByRole("group", { name: "Destination Main channel" })
    expect(destination).toHaveTextContent("Healthy")
    expect(destination).toHaveTextContent("Auto-publish disabled")
    expect(destination).toHaveTextContent("Configured")
    expect(destination).not.toHaveTextContent("TELEGRAM_BOT_TOKEN")

    fireEvent.change(screen.getByLabelText("Destination name"), { target: { value: "Backup channel" } })
    fireEvent.change(screen.getByLabelText("Telegram channel reference"), { target: { value: "@backup" } })
    const envName = screen.getByLabelText("Destination environment variable name")
    fireEvent.change(envName, { target: { value: "TELEGRAM_BACKUP_BOT_TOKEN" } })
    fireEvent.click(screen.getByRole("button", { name: "Create destination" }))
    await waitFor(() =>
      expect(createTelegramDestination).toHaveBeenCalledWith(
        expect.objectContaining({ targetRef: "@backup", secretRef: "TELEGRAM_BACKUP_BOT_TOKEN" })
      )
    )
    await waitFor(() => expect(envName).toHaveValue(""))
  })
})

function renderSettings() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { queryClient, ...render(
    <QueryClientProvider client={queryClient}>
      <NoticeProvider>
        <ContentSettingsPage />
      </NoticeProvider>
    </QueryClientProvider>
  ) }
}
