import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"
import { DirtyNavigationCoordinator } from "@/components/editorial/use-dirty-navigation"
import * as packageApi from "@/features/packages/api"
import type { ContentPackage, InstagramRevision, PlatformRevision, TelegramRevision } from "@/features/packages/types"
import * as api from "@/lib/editorial-api"
import type { VariantRevision } from "@/lib/editorial-types"
import { ApiError } from "@/lib/http"

vi.mock("@/features/packages/api", () => ({ approvePlatformRevision: vi.fn(), getPackage: vi.fn(), getPlatformRevision: vi.fn(), getPlatformRevisions: vi.fn(), rejectPlatformRevision: vi.fn(), saveManualPlatformRevision: vi.fn() }))
vi.mock("@/lib/editorial-api", () => ({ getAIProviderOptions: vi.fn(), getPromptVersionOptions: vi.fn(), getStoryEvidence: vi.fn(), regenerateVariant: vi.fn(), saveVariantRevision: vi.fn() }))

const revision: VariantRevision = { id: "rev-1", variantId: "variant-1", contentPackId: "pack-1", storyId: "story-1", parentRevisionId: null, generationAttemptId: null, revisionNumber: 1, content: { body: "Draft", parseMode: "HTML", buttons: [], mediaAssetIds: [], sourceUrl: null, mediaPolicy: "preserve", direction: "ltr", dryRun: false }, contentHash: "a".repeat(64), evidenceMap: [], validationResults: [{ gate: "telegram_schema", ok: true, reason: null }], approvalState: "pending_review", approvalNote: null, approvedAt: null, createdBy: "generation", origin: "generation", createdAt: "2026-07-12T08:00:00Z", providerProfile: null, resolvedModel: null }
const telegramRevision = (current: VariantRevision): TelegramRevision => ({ id: current.id, platform: "telegram", variantId: current.variantId, contentPackId: current.contentPackId, storyId: current.storyId, parentRevisionId: current.parentRevisionId, generationAttemptId: current.generationAttemptId, revisionNumber: current.revisionNumber, payload: { body: current.content.body, parseMode: current.content.parseMode, buttons: current.content.buttons, sourceItemId: null, sourceUrl: current.content.sourceUrl, mediaPolicy: current.content.mediaPolicy as TelegramRevision["payload"]["mediaPolicy"], mediaAssetIds: current.content.mediaAssetIds, direction: current.content.direction === "auto" ? "ltr" : current.content.direction, dryRun: current.content.dryRun }, contentHash: current.contentHash, evidenceCitations: current.evidenceMap, manualChecklist: [], validationResults: current.validationResults, validation: [], mediaPlan: current.content.mediaAssetIds, sourceMedia: [], approvalState: current.approvalState, approvalNote: current.approvalNote, approvedAt: current.approvedAt, createdBy: current.createdBy, origin: current.origin, providerProfile: current.providerProfile, resolvedModel: current.resolvedModel, promptVersion: null, createdAt: current.createdAt })
const pack = (current: PlatformRevision, variants: ContentPackage["variants"] = [{ id: current.variantId, platform: current.platform, currentRevision: current }]): ContentPackage => ({ id: "pack-1", storyId: "story-1", storyRevisionId: "story-rev-1", brandProfileId: "brand-1", status: current.approvalState, createdAt: current.createdAt, updatedAt: current.createdAt, variants })

function mockCommonQueries() {
  vi.mocked(api.getStoryEvidence).mockResolvedValue([])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
}

beforeEach(() => vi.resetAllMocks())
afterEach(() => vi.restoreAllMocks())

it("makes the approved exact-revision handoff visible after approval without a page reload", async () => {
  let current = telegramRevision(revision)
  vi.mocked(packageApi.getPackage).mockImplementation(async () => pack(current))
  vi.mocked(packageApi.getPlatformRevision).mockImplementation(async () => current)
  vi.mocked(packageApi.getPlatformRevisions).mockImplementation(async () => [current])
  vi.mocked(packageApi.approvePlatformRevision).mockImplementation(async () => { current = { ...current, approvalState: "approved", approvedAt: "2026-07-12T09:00:00Z" }; return current })
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" initialRevisionId="rev-1" /></TestApp>)
  fireEvent.click(await screen.findByRole("button", { name: "Approve revision" }))
  expect(await screen.findByRole("link", { name: "Preview, schedule, or publish approved revision" })).toHaveAttribute("href", "/review/rev-1")
  await waitFor(() => expect(packageApi.getPackage).toHaveBeenCalledTimes(2))
})

it("switches platforms without mixing their immutable revision histories", async () => {
  const telegram = telegramRevision(revision)
  const instagramRevision: InstagramRevision = {
    ...telegram,
    id: "rev-instagram-4",
    platform: "instagram",
    variantId: "variant-instagram",
    revisionNumber: 4,
    contentHash: "4".repeat(64),
    payload: {
      hook: "Grounded hook",
      caption: "Grounded Instagram caption",
      cta: "Read the evidence",
      hashtags: ["#news"],
      altText: "A summary card",
      carousel: [],
      citations: [],
      manualChecklist: ["Verify copy"],
    },
    manualChecklist: ["Verify copy"],
    mediaPlan: [],
  }
  const variants: ContentPackage["variants"] = [
    { id: "variant-1", platform: "telegram", currentRevision: telegram },
    { id: "variant-instagram", platform: "instagram", currentRevision: instagramRevision },
    { id: "variant-x", platform: "x", currentRevision: null },
    { id: "variant-blog", platform: "blog", currentRevision: null },
  ]
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(telegram, variants))
  vi.mocked(packageApi.getPlatformRevisions).mockImplementation(async (variantId) => variantId === "variant-1" ? [telegram] : variantId === "variant-instagram" ? [instagramRevision] : [])
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" /></TestApp>)

  expect(await screen.findByRole("heading", { name: "Multi-platform editorial studio" })).toBeInTheDocument()
  expect(screen.getByRole("tablist", { name: "Package platforms" })).toBeInTheDocument()
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Telegram", "Instagram", "X", "Blog"])
  fireEvent.click(screen.getByRole("tab", { name: "Instagram" }))
  expect(await screen.findByRole("region", { name: "Instagram preview" })).toBeInTheDocument()
  expect(screen.getByRole("tab", { name: "Instagram" })).toHaveAttribute("aria-selected", "true")
  expect(screen.getByRole("button", { name: /Revision 4/ })).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Revision 1/ })).not.toBeInTheDocument()
})

it("fences media reordering while the manual editor has unsaved copy", async () => {
  const telegram = telegramRevision(revision)
  const instagram: InstagramRevision = {
    ...telegram,
    id: "rev-instagram-media",
    platform: "instagram",
    variantId: "variant-instagram",
    payload: {
      hook: "Grounded hook",
      caption: "Grounded caption",
      cta: "Read more",
      hashtags: [],
      altText: "Two cards",
      carousel: [1, 2].map((order) => ({ order, headline: `Card ${order}`, body: `Body ${order}`, media: { mediaAssetId: null, role: "slide", order, altText: `Card ${order}`, manualBrief: "Create manually", imagePrompt: null } })),
      citations: [],
      manualChecklist: ["Verify cards"],
    },
    manualChecklist: ["Verify cards"],
    mediaPlan: [],
  }
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(instagram))
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValue([instagram])
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" /></TestApp>)

  expect(await screen.findByRole("button", { name: "Move slide 2 up" })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Unsaved manual caption" } })
  await waitFor(() => expect(screen.queryByRole("button", { name: "Move slide 2 up" })).not.toBeInTheDocument())
  expect(packageApi.saveManualPlatformRevision).not.toHaveBeenCalled()
})

it("fences manual copy and review actions while a media child revision is pending", async () => {
  const telegram = telegramRevision(revision)
  const instagram: InstagramRevision = {
    ...telegram,
    id: "rev-instagram-reorder",
    platform: "instagram",
    variantId: "variant-instagram",
    payload: {
      hook: "Grounded hook",
      caption: "Grounded caption",
      cta: "Read more",
      hashtags: [],
      altText: "Two cards",
      carousel: [1, 2].map((order) => ({ order, headline: `Card ${order}`, body: `Body ${order}`, media: { mediaAssetId: null, role: "slide", order, altText: `Card ${order}`, manualBrief: "Create manually", imagePrompt: null } })),
      citations: [],
      manualChecklist: ["Verify cards"],
    },
    manualChecklist: ["Verify cards"],
    mediaPlan: [],
  }
  let resolveSave!: (value: PlatformRevision) => void
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(instagram))
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValue([instagram])
  vi.mocked(packageApi.saveManualPlatformRevision).mockReturnValue(new Promise<PlatformRevision>((resolve) => { resolveSave = resolve }))
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" /></TestApp>)
  fireEvent.click(await screen.findByRole("button", { name: "Move slide 2 up" }))

  const caption = screen.getByLabelText("Caption")
  await waitFor(() => expect(caption).toBeDisabled())
  expect(screen.getByRole("button", { name: "Approve revision" })).toBeDisabled()
  expect(screen.getByLabelText("Rejection reason")).toBeDisabled()
  expect(screen.getByRole("tab", { name: "Instagram" })).toBeDisabled()
  expect(screen.getByRole("button", { name: /Revision 1/ })).toBeDisabled()
  expect(screen.queryByRole("button", { name: "Move slide 2 up" })).not.toBeInTheDocument()
  expect(caption).toHaveValue("Grounded caption")
  resolveSave({ ...instagram, id: "rev-instagram-reorder-2", parentRevisionId: instagram.id, revisionNumber: 2, payload: { ...instagram.payload, carousel: [...instagram.payload.carousel].reverse().map((item, index) => ({ ...item, order: index + 1, media: { ...item.media, order: index + 1 } })) } })
  await waitFor(() => expect(packageApi.saveManualPlatformRevision).toHaveBeenCalledTimes(1))
})

it("binds manual approval to the selected immutable revision and exposes its handoff", async () => {
  const telegram = telegramRevision(revision)
  let instagram: InstagramRevision = {
    ...telegram,
    id: "rev-instagram-review",
    platform: "instagram",
    variantId: "variant-instagram",
    payload: { hook: "Grounded hook", caption: "Grounded caption", cta: "Read more", hashtags: [], altText: "Summary card", carousel: [], citations: [], manualChecklist: ["Verify copy"] },
    manualChecklist: ["Verify copy"],
    mediaPlan: [],
  }
  vi.mocked(packageApi.getPackage).mockImplementation(async () => pack(instagram))
  vi.mocked(packageApi.getPlatformRevisions).mockImplementation(async () => [instagram])
  vi.mocked(packageApi.approvePlatformRevision).mockImplementation(async (_revisionId, input) => {
    expect(input).toEqual({ expectedContentHash: instagram.contentHash, note: null })
    instagram = { ...instagram, approvalState: "approved", approvedAt: "2026-07-13T09:00:00Z" }
    return instagram
  })
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" /></TestApp>)
  fireEvent.click(await screen.findByRole("button", { name: "Approve revision" }))

  await waitFor(() => expect(packageApi.approvePlatformRevision).toHaveBeenCalledWith("rev-instagram-review", { expectedContentHash: "a".repeat(64), note: null }))
  expect(await screen.findByRole("link", { name: "Preview, schedule, or publish approved revision" })).toHaveAttribute("href", "/review/rev-instagram-review")
})

it("resets manual review outcome and rejection state when selecting another revision", async () => {
  const telegram = telegramRevision(revision)
  const first: InstagramRevision = {
    ...telegram,
    id: "rev-instagram-1",
    platform: "instagram",
    variantId: "variant-instagram",
    payload: { hook: "First hook", caption: "First caption", cta: "Read more", hashtags: [], altText: "First card", carousel: [], citations: [], manualChecklist: ["Verify copy"] },
    manualChecklist: ["Verify copy"],
    mediaPlan: [],
  }
  let second: InstagramRevision = { ...first, id: "rev-instagram-2", parentRevisionId: first.id, revisionNumber: 2, payload: { ...first.payload, caption: "Second caption" } }
  vi.mocked(packageApi.getPackage).mockImplementation(async () => pack(second))
  vi.mocked(packageApi.getPlatformRevisions).mockImplementation(async () => [second, first])
  vi.mocked(packageApi.approvePlatformRevision).mockImplementation(async () => {
    second = { ...second, approvalState: "approved", approvedAt: "2026-07-13T09:00:00Z" }
    return second
  })
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" /></TestApp>)
  const rejection = await screen.findByLabelText("Rejection reason")
  fireEvent.change(rejection, { target: { value: "Reason for revision two" } })
  fireEvent.click(screen.getByRole("button", { name: "Approve revision" }))
  expect(await screen.findByText("Revision approved")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: /Revision 1/ }))

  await waitFor(() => expect(screen.getByLabelText("Rejection reason")).toHaveValue(""))
  expect(screen.queryByText("Revision approved")).not.toBeInTheDocument()
  expect(screen.getByLabelText("Caption")).toHaveValue("First caption")
})

it("fences Telegram approval while media reordering creates a child revision", async () => {
  const current = { ...revision, content: { ...revision.content, mediaAssetIds: ["media-1", "media-2"] } }
  const platformCurrent = telegramRevision(current)
  let resolveSave!: (value: VariantRevision) => void
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(platformCurrent))
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValue([platformCurrent])
  vi.mocked(api.saveVariantRevision).mockReturnValue(new Promise<VariantRevision>((resolve) => { resolveSave = resolve }))
  mockCommonQueries()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" /></TestApp>)
  const approve = await screen.findByRole("button", { name: "Approve revision" })
  expect(approve).toBeEnabled()
  fireEvent.click(screen.getByRole("button", { name: "Move Telegram item 2 up" }))

  await waitFor(() => expect(approve).toBeDisabled())
  const message = screen.getByLabelText("Telegram message")
  expect(message).toBeDisabled()
  expect(screen.getByRole("tab", { name: "Telegram" })).toBeDisabled()
  expect(screen.getByRole("button", { name: /Revision 1/ })).toBeDisabled()
  expect(message).toHaveValue("Draft")
  resolveSave({ ...current, id: "rev-2", parentRevisionId: current.id, revisionNumber: 2, content: { ...current.content, mediaAssetIds: ["media-2", "media-1"] } })
  await waitFor(() => expect(api.saveVariantRevision).toHaveBeenCalledTimes(1))
})

it("reloads the actual latest same-variant revision after 409 and reapplies the complete stash once", async () => {
  const rev2 = { ...revision, id: "rev-2", revisionNumber: 2, contentHash: "2".repeat(64), content: { ...revision.content, body: "Revision two", buttons: [{ text: "Source", url: "https://example.com" }], mediaAssetIds: ["media-2"] } }
  const rev3 = { ...rev2, id: "rev-3", revisionNumber: 3, contentHash: "3".repeat(64), content: { ...rev2.content, body: "Server revision three" }, createdAt: "2026-07-12T09:00:00Z" }
  const platformRev2 = telegramRevision(rev2)
  const platformRev3 = telegramRevision(rev3)
  let resolveLatest!: (value: PlatformRevision[]) => void
  const latest = new Promise<PlatformRevision[]>((resolve) => { resolveLatest = resolve })
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(platformRev2))
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(platformRev2)
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValueOnce([platformRev2]).mockReturnValueOnce(latest)
  mockCommonQueries()
  vi.mocked(api.saveVariantRevision).mockRejectedValue(new ApiError("Conflict", 409, "revision changed"))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" initialRevisionId="rev-2" /></TestApp>)
  const body = await screen.findByLabelText("Telegram message")
  fireEvent.change(body, { target: { value: "Operator conflict draft" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  await screen.findByText("A newer revision exists. Reload before saving.")
  fireEvent.click(screen.getByRole("button", { name: "Reload latest" }))
  resolveLatest([platformRev2, platformRev3])
  expect(await screen.findByText(`Loaded revision rev-3 · hash ${"3".repeat(64)}`)).toBeInTheDocument()
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Server revision three")
  fireEvent.click(screen.getByRole("button", { name: "Reapply my edits" }))
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Operator conflict draft")
  expect(screen.getByLabelText("Button 1 text")).toHaveValue("Source")
  expect(screen.getByLabelText("Media asset assignments")).toHaveValue("media-2")
  expect(screen.queryByRole("button", { name: "Reapply my edits" })).not.toBeInTheDocument()
})

it("keeps dirty edits when timeline navigation is cancelled and discards only after confirmation", async () => {
  const rev1 = { ...revision, id: "rev-1", revisionNumber: 1, contentHash: "1".repeat(64) }
  const rev2 = { ...revision, id: "rev-2", revisionNumber: 2, contentHash: "2".repeat(64), content: { ...revision.content, body: "Revision two" } }
  const platformRev1 = telegramRevision(rev1)
  const platformRev2 = telegramRevision(rev2)
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(platformRev2))
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(platformRev2)
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValue([platformRev2, platformRev1])
  mockCommonQueries()
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" initialRevisionId="rev-2" /></TestApp>)
  fireEvent.change(await screen.findByLabelText("Telegram message"), { target: { value: "Unsaved operator body" } })
  fireEvent.click(screen.getByRole("button", { name: /Revision 1/ }))
  expect(screen.getByText(new RegExp(`Loaded revision rev-2`))).toBeInTheDocument()
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Unsaved operator body")
  fireEvent.click(screen.getByRole("button", { name: /Revision 1/ }))
  expect(await screen.findByText(new RegExp(`Loaded revision rev-1`))).toBeInTheDocument()
  expect(confirm).toHaveBeenCalledTimes(2)
})

it.each(["body", "buttons", "media"] as const)("guards an outside same-origin SPA link while %s edits are dirty", async (field) => {
  const platformRevision = telegramRevision(revision)
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(platformRevision))
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValue([platformRevision])
  mockCommonQueries()
  const navigate = vi.fn()
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<TestApp client={client}><a href="/inbox" onClick={(event) => { event.preventDefault(); navigate() }}>Inbox navigation</a><ContentPackWorkspace packId="pack-1" /></TestApp>)
  await screen.findByLabelText("Telegram message")
  if (field === "body") fireEvent.change(screen.getByLabelText("Telegram message"), { target: { value: "Unsaved body" } })
  if (field === "buttons") fireEvent.click(screen.getByRole("button", { name: "Add button" }))
  if (field === "media") fireEvent.change(screen.getByLabelText("Media asset assignments"), { target: { value: "media-unsaved" } })
  fireEvent.click(screen.getByRole("link", { name: "Inbox navigation" }))
  expect(navigate).not.toHaveBeenCalled()
  expect(screen.getByText("Changes will create a pending review revision")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("link", { name: "Inbox navigation" }))
  expect(navigate).toHaveBeenCalledTimes(1)
  expect(confirm).toHaveBeenCalledTimes(2)
})

it("prompts once for handoff, leaks no bypass after cancel, and keeps timeline on its local guard", async () => {
  const rev1 = { ...revision, id: "rev-1", revisionNumber: 1, contentHash: "1".repeat(64) }
  const rev2 = { ...revision, id: "rev-2", revisionNumber: 2, contentHash: "2".repeat(64), approvalState: "approved" as const, content: { ...revision.content, body: "Approved body" } }
  const platformRev1 = telegramRevision(rev1)
  const platformRev2 = telegramRevision(rev2)
  vi.mocked(packageApi.getPackage).mockResolvedValue(pack(platformRev2))
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(platformRev2)
  vi.mocked(packageApi.getPlatformRevisions).mockResolvedValue([platformRev2, platformRev1])
  mockCommonQueries()
  const sidebar = vi.fn()
  const observed = vi.fn((event: Event) => event.preventDefault())
  document.addEventListener("click", observed)
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(true).mockReturnValueOnce(false).mockReturnValueOnce(false).mockReturnValueOnce(true)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<TestApp client={client}><a href="/inbox" onClick={(event) => { event.preventDefault(); sidebar() }}>Sidebar inbox</a><ContentPackWorkspace packId="pack-1" initialRevisionId="rev-2" /></TestApp>)
  fireEvent.change(await screen.findByLabelText("Telegram message"), { target: { value: "Dirty approved body" } })
  const handoff = screen.getByRole("link", { name: "Preview, schedule, or publish approved revision" })
  fireEvent.click(handoff)
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(observed).toHaveBeenCalledTimes(1)
  fireEvent.click(handoff)
  expect(confirm).toHaveBeenCalledTimes(2)
  expect(observed).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Dirty approved body")
  fireEvent.click(screen.getByRole("link", { name: "Sidebar inbox" }))
  expect(confirm).toHaveBeenCalledTimes(3)
  expect(sidebar).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: /Revision 1/ }))
  expect(confirm).toHaveBeenCalledTimes(4)
  expect(await screen.findByText(/Loaded revision rev-1/)).toBeInTheDocument()
  document.removeEventListener("click", observed)
})

function TestApp({ client, children }: { client: QueryClient; children: React.ReactNode }) {
  return <QueryClientProvider client={client}><DirtyNavigationCoordinator />{children}</QueryClientProvider>
}
