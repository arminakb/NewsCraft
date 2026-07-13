import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"
import { DirtyNavigationCoordinator } from "@/components/editorial/use-dirty-navigation"
import * as api from "@/lib/editorial-api"
import type { ContentPackDetail, VariantRevision } from "@/lib/editorial-types"
import { ApiError } from "@/lib/http"

vi.mock("@/lib/editorial-api", () => ({ approveVariantRevision: vi.fn(), getAIProviderOptions: vi.fn(), getContentPack: vi.fn(), getPromptVersionOptions: vi.fn(), getStoryEvidence: vi.fn(), regenerateVariant: vi.fn(), rejectVariantRevision: vi.fn(), saveVariantRevision: vi.fn() }))

const revision: VariantRevision = { id: "rev-1", variantId: "variant-1", contentPackId: "pack-1", storyId: "story-1", parentRevisionId: null, generationAttemptId: null, revisionNumber: 1, content: { body: "Draft", parseMode: "HTML", buttons: [], mediaAssetIds: [], sourceUrl: null, mediaPolicy: "preserve", direction: "ltr", dryRun: false }, contentHash: "a".repeat(64), evidenceMap: [], validationResults: [{ gate: "telegram_schema", ok: true, reason: null }], approvalState: "pending_review", approvalNote: null, approvedAt: null, createdBy: "generation", origin: "generation", createdAt: "2026-07-12T08:00:00Z", providerProfile: null, resolvedModel: null }
const pack = (current: VariantRevision): ContentPackDetail => ({ id: "pack-1", storyId: "story-1", storyRevisionId: "story-rev-1", brandProfileId: "brand-1", status: current.approvalState, createdAt: current.createdAt, updatedAt: current.createdAt, lastFailure: null, jobId: null, variants: [{ id: "variant-1", platform: "telegram" }], variantRevisions: { "variant-1": [current] } })

beforeEach(() => vi.resetAllMocks())
afterEach(() => vi.restoreAllMocks())

it("makes the approved exact-revision handoff visible after approval without a page reload", async () => {
  let current = revision
  vi.mocked(api.getContentPack).mockImplementation(async () => pack(current))
  vi.mocked(api.getStoryEvidence).mockResolvedValue([])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
  vi.mocked(api.approveVariantRevision).mockImplementation(async () => { current = { ...revision, approvalState: "approved", approvedAt: "2026-07-12T09:00:00Z" }; return current })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" initialRevisionId="rev-1" /></TestApp>)
  fireEvent.click(await screen.findByRole("button", { name: "Approve revision" }))
  expect(await screen.findByRole("link", { name: "Preview, schedule, or publish approved revision" })).toHaveAttribute("href", "/review/rev-1")
  await waitFor(() => expect(api.getContentPack).toHaveBeenCalledTimes(2))
})

it("reloads the actual latest same-variant revision after 409 and reapplies the complete stash once", async () => {
  const rev2 = { ...revision, id: "rev-2", revisionNumber: 2, contentHash: "2".repeat(64), content: { ...revision.content, body: "Revision two", buttons: [{ text: "Source", url: "https://example.com" }], mediaAssetIds: ["media-2"] } }
  const rev3 = { ...rev2, id: "rev-3", revisionNumber: 3, contentHash: "3".repeat(64), content: { ...rev2.content, body: "Server revision three" }, createdAt: "2026-07-12T09:00:00Z" }
  let resolveLatest!: (value: ContentPackDetail) => void
  const latest = new Promise<ContentPackDetail>((resolve) => { resolveLatest = resolve })
  vi.mocked(api.getContentPack).mockResolvedValueOnce(pack(rev2)).mockReturnValueOnce(latest)
  vi.mocked(api.getStoryEvidence).mockResolvedValue([])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
  vi.mocked(api.saveVariantRevision).mockRejectedValue(new ApiError("Conflict", 409, "revision changed"))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<TestApp client={client}><ContentPackWorkspace packId="pack-1" initialRevisionId="rev-2" /></TestApp>)
  const body = await screen.findByLabelText("Telegram message")
  fireEvent.change(body, { target: { value: "Operator conflict draft" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  await screen.findByText("A newer revision exists. Reload before saving.")
  fireEvent.click(screen.getByRole("button", { name: "Reload latest" }))
  resolveLatest({ ...pack(rev3), variantRevisions: { "variant-1": [rev2, rev3] } })
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
  vi.mocked(api.getContentPack).mockResolvedValue({ ...pack(rev2), variantRevisions: { "variant-1": [rev2, rev1] } })
  vi.mocked(api.getStoryEvidence).mockResolvedValue([])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
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
  vi.mocked(api.getContentPack).mockResolvedValue(pack(revision))
  vi.mocked(api.getStoryEvidence).mockResolvedValue([])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
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
  vi.mocked(api.getContentPack).mockResolvedValue({ ...pack(rev2), variantRevisions: { "variant-1": [rev2, rev1] } })
  vi.mocked(api.getStoryEvidence).mockResolvedValue([])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
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
