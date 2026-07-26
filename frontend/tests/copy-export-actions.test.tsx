import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"

import { decodeExportOutcome } from "@/features/packages/api"
import { CopyExportActions } from "@/features/packages/components/copy-export-actions"
import type {
  BlogRevision,
  InstagramRevision,
  PlatformRevision,
  TelegramRevision,
  XRevision,
} from "@/features/packages/types"

const ids = {
  revision: "11111111-1111-4111-8111-111111111111",
  variant: "22222222-2222-4222-8222-222222222222",
  pack: "33333333-3333-4333-8333-333333333333",
  story: "44444444-4444-4444-8444-444444444444",
  storyRevision: "55555555-5555-4555-8555-555555555555",
  export: "66666666-6666-4666-8666-666666666666",
  otherPack: "77777777-7777-4777-8777-777777777777",
  otherRevision: "88888888-8888-4888-8888-888888888888",
  otherVariant: "99999999-9999-4999-8999-999999999999",
}

const common = {
  id: ids.revision,
  variantId: ids.variant,
  contentPackId: ids.pack,
  storyId: ids.story,
  parentRevisionId: null,
  generationAttemptId: null,
  revisionNumber: 1,
  contentHash: "a".repeat(64),
  evidenceCitations: [],
  manualChecklist: [],
  validationResults: [],
  validation: [],
  mediaPlan: [],
  sourceMedia: [],
  approvalState: "approved" as const,
  approvalNote: null,
  approvedAt: "2026-07-13T08:00:00Z",
  createdBy: "operator",
  origin: "operator" as const,
  providerProfile: null,
  resolvedModel: null,
  promptVersion: null,
  createdAt: "2026-07-13T07:00:00Z",
}

const xRevision: XRevision = {
  ...common,
  platform: "x",
  payload: {
    mode: "thread",
    posts: [
      { order: 2, text: "Second post", media: [], citations: [] },
      { order: 1, text: "First post", media: [], citations: [] },
    ],
    linkStrategy: "last_post",
    manualChecklist: [],
  },
}

const telegramRevision: TelegramRevision = {
  ...common,
  platform: "telegram",
  payload: {
    body: "Formatted <b>message</b>",
    parseMode: "HTML",
    buttons: [],
    sourceItemId: null,
    sourceUrl: null,
    mediaPolicy: "omit",
    mediaAssetIds: [],
    direction: "ltr",
    dryRun: false,
  },
}

const instagramRevision: InstagramRevision = {
  ...common,
  platform: "instagram",
  payload: {
    hook: "Verified hook",
    caption: "Grounded caption",
    cta: "Read the evidence",
    hashtags: ["#news", "#verified"],
    altText: "Summary card",
    carousel: [],
    citations: [],
    manualChecklist: [],
  },
}

const blogRevision: BlogRevision = {
  ...common,
  platform: "blog",
  payload: {
    title: "Grounded report",
    slug: "grounded-report",
    excerpt: "A summary",
    bodyMarkdown: "# Grounded\n\n[Source](https://example.com/report)\n\n<script>alert(1)</script>",
    headings: ["Grounded"],
    citations: [],
    tags: ["news"],
    seoDescription: "Grounded report summary",
    heroMedia: null,
    canonicalSources: [],
    manualChecklist: [],
  },
}

beforeEach(() => {
  vi.restoreAllMocks()
})

it("copies the selected full X thread and announces success accessibly", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  setClipboard(writeText)
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} />)

  fireEvent.click(screen.getByRole("button", { name: "Copy full X thread" }))

  await waitFor(() => expect(writeText).toHaveBeenCalledWith("1/2 First post\n\n2/2 Second post"))
  expect(screen.getByRole("status")).toHaveTextContent("Copied X thread")
})

it("keeps selected-revision copy available but requires every intended package revision to be approved", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  setClipboard(writeText)
  render(<CopyExportActions
    revision={xRevision}
    intendedRevisions={[
      ...intendedRevisionsFor(xRevision),
      { variantId: ids.otherVariant, revisionId: ids.otherRevision, approvalState: "pending_review" },
    ]}
  />)

  const copy = screen.getByRole("button", { name: "Copy full X thread" })
  expect(copy).toBeEnabled()
  fireEvent.click(copy)
  await waitFor(() => expect(writeText).toHaveBeenCalledOnce())
  expect(screen.getByRole("button", { name: "Export package" })).toBeDisabled()
  expect(screen.getByText("Approve every intended package revision before exporting.")).toBeInTheDocument()
})

it("offers exact platform copy representations and individual X post buttons", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  setClipboard(writeText)
  const renderedHtml = '<h1>Grounded</h1>\n<p><a href="https://example.com/report">Source</a></p>\n<p>alert(1)</p>'
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({
    revision_id: blogRevision.id,
    content_hash: blogRevision.contentHash,
    platform: "blog",
    html: renderedHtml,
  }))
  const view = render(<CopyExportActions revision={telegramRevision} intendedRevisions={intendedRevisionsFor(telegramRevision)} />)

  fireEvent.click(screen.getByRole("button", { name: "Copy Telegram formatted message" }))
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith("Formatted <b>message</b>"))

  view.rerender(<CopyExportActions revision={instagramRevision} intendedRevisions={intendedRevisionsFor(instagramRevision)} />)
  fireEvent.click(screen.getByRole("button", { name: "Copy Instagram caption and hashtags" }))
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(
    "Verified hook\n\nGrounded caption\n\nRead the evidence\n\n#news #verified",
  ))

  view.rerender(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} />)
  fireEvent.click(screen.getByRole("button", { name: "Copy X post 2" }))
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith("Second post"))

  view.rerender(<CopyExportActions revision={blogRevision} intendedRevisions={intendedRevisionsFor(blogRevision)} />)
  fireEvent.click(screen.getByRole("button", { name: "Copy Blog Markdown" }))
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(blogRevision.payload.bodyMarkdown))
  fireEvent.click(screen.getByRole("button", { name: "Copy Blog HTML" }))
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(renderedHtml))
  expect(fetchSpy).toHaveBeenCalledWith(
    `/api/backend/platform-variant-revisions/${blogRevision.id}/rendered-html`,
    undefined,
  )
  expect(renderedHtml).toContain("<h1>Grounded</h1>")
  expect(renderedHtml).toContain('href="https://example.com/report"')
  expect(renderedHtml).not.toContain("<script")
})

it("keeps failed clipboard content focused and selected behind a durable error", async () => {
  setClipboard(vi.fn().mockRejectedValue(new Error("Permission denied")))
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} />)

  fireEvent.click(screen.getByRole("button", { name: "Copy full X thread" }))

  const fallback = await screen.findByRole("textbox", { name: "Manual copy content" })
  const expected = "1/2 First post\n\n2/2 Second post"
  expect(screen.getByRole("alert")).toHaveTextContent("Clipboard access failed")
  expect(fallback).toHaveValue(expected)
  expect(fallback).toHaveAttribute("data-testid", "direction-boundary")
  expect(fallback).toHaveAttribute("dir", "auto")
  await waitFor(() => {
    expect(fallback).toHaveFocus()
    expect(fallback).toHaveProperty("selectionStart", 0)
    expect(fallback).toHaveProperty("selectionEnd", expected.length)
  })
})

it("submits export choices, polls the durable job, and exposes downloads only after success", async () => {
  let resolveStatus!: (response: Response) => void
  const statusResponse = new Promise<Response>((resolve) => { resolveStatus = resolve })
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse({ job_id: ids.export, status: "queued", deduplicated: false }, 202))
    .mockReturnValueOnce(statusResponse)
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} pollIntervalMs={1} />)

  fireEvent.click(screen.getByRole("checkbox", { name: "HTML" }))
  fireEvent.click(screen.getByRole("checkbox", { name: "Include media" }))
  fireEvent.click(screen.getByRole("button", { name: "Export package" }))

  await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith(
    `/api/backend/content-packs/${ids.pack}/exports`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        content_pack_id: ids.pack,
        revision_ids: [ids.revision],
        formats: ["markdown", "html"],
        include_media: true,
      }),
    }),
  ))
  expect(screen.queryByRole("link", { name: /Download/ })).not.toBeInTheDocument()

  await act(async () => {
    resolveStatus(jsonResponse(succeededExportWire()))
  })

  const download = await screen.findByRole("link", { name: "Download bundle.zip" })
  expect(download).toHaveAttribute(
    "href",
    `/api/backend/exports/${ids.export}/download/bundle.zip`,
  )
  expect(screen.getByText("Export ready")).toBeInTheDocument()
  expect(screen.getByRole("status", { name: "Export status" })).toHaveTextContent(`succeeded · ${ids.export}`)
})

it("decodes an exact expired export tombstone without inventing downloads", () => {
  const outcome = decodeExportOutcome(expiredExportWire())

  expect(outcome).toMatchObject({
    exportId: ids.export,
    status: "succeeded",
    finishedAt: "2026-07-13T09:00:00Z",
    downloads: [],
    errorCode: "export_expired",
    errorMessage: "Export artifact expired under retention policy",
  })
  expect(outcome.artifact).toEqual({
    exportId: ids.export,
    contentPackId: ids.pack,
    state: "expired",
    expiredAt: "2026-07-13T10:00:00Z",
  })
})

it("rejects an expired export tombstone with extra fields or advertised downloads", () => {
  const withExtraArtifactField = expiredExportWire()
  Object.assign(withExtraArtifactField.artifact, { manifest: null })
  const withDownload = expiredExportWire()
  withDownload.downloads = [`/exports/${ids.export}/download/bundle.zip`]

  expect(() => decodeExportOutcome(withExtraArtifactField)).toThrow("Invalid export artifact")
  expect(() => decodeExportOutcome(withDownload)).toThrow("Invalid export outcome")
})

it("surfaces an expired polled export without a ready state or download link", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse({ job_id: ids.export, status: "queued", deduplicated: false }, 202))
    .mockResolvedValueOnce(jsonResponse(expiredExportWire()))
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} pollIntervalMs={1} />)

  fireEvent.click(screen.getByRole("button", { name: "Export package" }))

  expect(await screen.findByText("Export expired")).toBeInTheDocument()
  expect(screen.getByText("Export artifact expired under retention policy")).toBeInTheDocument()
  expect(screen.getByRole("status", { name: "Export status" })).toHaveTextContent(`succeeded · ${ids.export}`)
  expect(screen.queryByText("Export ready")).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: /Download/ })).not.toBeInTheDocument()
})

it("retries a transient poll failure against the same export ID until queued then succeeded", async () => {
  let resolveQueued!: (response: Response) => void
  let resolveSucceeded!: (response: Response) => void
  const queuedResponse = new Promise<Response>((resolve) => { resolveQueued = resolve })
  const succeededResponse = new Promise<Response>((resolve) => { resolveSucceeded = resolve })
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse({ job_id: ids.export, status: "queued", deduplicated: false }, 202))
    .mockResolvedValueOnce(new Response("temporarily unavailable", { status: 503, statusText: "Service Unavailable" }))
    .mockReturnValueOnce(queuedResponse)
    .mockReturnValueOnce(succeededResponse)
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} pollIntervalMs={1} />)

  fireEvent.click(screen.getByRole("button", { name: "Export package" }))

  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(3))
  expect(fetchSpy.mock.calls.slice(1).every(([url]) => url === `/api/backend/exports/${ids.export}`)).toBe(true)
  expect(screen.queryByRole("link", { name: /Download/ })).not.toBeInTheDocument()

  await act(async () => resolveQueued(jsonResponse(queuedExportWire())))
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(4))
  expect(fetchSpy.mock.calls.slice(1).every(([url]) => url === `/api/backend/exports/${ids.export}`)).toBe(true)
  expect(screen.queryByRole("link", { name: /Download/ })).not.toBeInTheDocument()

  await act(async () => resolveSucceeded(jsonResponse(succeededExportWire())))
  expect(await screen.findByRole("link", { name: "Download bundle.zip" })).toBeInTheDocument()
})

it("keeps manifest validation bound to the revision set submitted for the accepted job when current revisions rerender", async () => {
  let resolveOriginalPoll!: (response: Response) => void
  const originalPoll = new Promise<Response>((resolve) => { resolveOriginalPoll = resolve })
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse({ job_id: ids.export, status: "queued", deduplicated: false }, 202))
    .mockReturnValueOnce(originalPoll)
    .mockResolvedValueOnce(jsonResponse(succeededExportWire()))
  const view = render(
    <CopyExportActions
      revision={xRevision}
      intendedRevisions={intendedRevisionsFor(xRevision)}
      pollIntervalMs={1}
    />,
  )

  fireEvent.click(screen.getByRole("button", { name: "Export package" }))
  await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
  expect(fetchSpy).toHaveBeenNthCalledWith(1, `/api/backend/content-packs/${ids.pack}/exports`, expect.objectContaining({
    body: expect.stringContaining(`"revision_ids":["${ids.revision}"]`),
  }))

  view.rerender(
    <CopyExportActions
      revision={xRevision}
      intendedRevisions={[{
        variantId: ids.variant,
        revisionId: ids.otherRevision,
        approvalState: "approved",
      }]}
      pollIntervalMs={1}
    />,
  )
  await act(async () => resolveOriginalPoll(jsonResponse(succeededExportWire())))

  expect(await screen.findByRole("link", { name: "Download bundle.zip" })).toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  expect(fetchSpy).toHaveBeenCalledTimes(2)
})

it("does not expose downloads from an export artifact bound to another content pack", async () => {
  const mismatched = succeededExportWire()
  mismatched.artifact.content_pack_id = ids.otherPack
  mismatched.artifact.manifest.content_pack_id = ids.otherPack
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse({ job_id: ids.export, status: "queued", deduplicated: false }, 202))
    .mockResolvedValueOnce(jsonResponse(mismatched))
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} pollIntervalMs={1} />)

  fireEvent.click(screen.getByRole("button", { name: "Export package" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("Export content package identity mismatch")
  expect(screen.queryByRole("link", { name: /Download/ })).not.toBeInTheDocument()
})

it("does not expose downloads when the manifest revision set differs from the explicit intended set", async () => {
  const mismatched = succeededExportWire()
  mismatched.artifact.manifest.variants[0].revision_id = ids.otherRevision
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(jsonResponse({ job_id: ids.export, status: "queued", deduplicated: false }, 202))
    .mockResolvedValueOnce(jsonResponse(mismatched))
  render(<CopyExportActions revision={xRevision} intendedRevisions={intendedRevisionsFor(xRevision)} pollIntervalMs={1} />)

  fireEvent.click(screen.getByRole("button", { name: "Export package" }))

  expect(await screen.findByRole("alert")).toHaveTextContent("Export revision identity mismatch")
  expect(screen.queryByRole("link", { name: /Download/ })).not.toBeInTheDocument()
})

it("rejects traversal in server-provided export download paths", () => {
  const unsafe = succeededExportWire()
  unsafe.downloads = [`/exports/${ids.export}/download/../secret.txt`]

  expect(() => decodeExportOutcome(unsafe)).toThrow("Invalid export outcome")
})

function setClipboard(writeText: (value: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  })
}

function intendedRevisionsFor(revision: PlatformRevision) {
  return [{
    variantId: revision.variantId,
    revisionId: revision.id,
    approvalState: revision.approvalState,
  }]
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function succeededExportWire() {
  return {
    export_id: ids.export,
    status: "succeeded",
    finished_at: "2026-07-13T09:00:00Z",
    artifact: {
      export_id: ids.export,
      content_pack_id: ids.pack,
      state: "complete",
      manifest_file: "manifest.json",
      manifest_sha256: "b".repeat(64),
      archive_file: "bundle.zip",
      archive_sha256: "c".repeat(64),
      manifest: {
        schema_version: "newscraft-export-v1",
        content_pack_id: ids.pack,
        story_revision_id: ids.storyRevision,
        created_at: "2026-07-13T08:00:00Z",
        variants: [{
          platform: "x",
          platform_variant_id: ids.variant,
          revision_id: ids.revision,
          content_hash: "a".repeat(64),
          approval_state: "approved",
          evidence_urls: [],
        }],
        files: [],
      },
    },
    downloads: [`/exports/${ids.export}/download/bundle.zip`],
    error_code: null,
    error_message: null,
  }
}

function expiredExportWire() {
  return {
    export_id: ids.export,
    status: "succeeded",
    finished_at: "2026-07-13T09:00:00Z",
    artifact: {
      export_id: ids.export,
      content_pack_id: ids.pack,
      state: "expired",
      expired_at: "2026-07-13T10:00:00Z",
    },
    downloads: [] as string[],
    error_code: "export_expired",
    error_message: "Export artifact expired under retention policy",
  }
}

function queuedExportWire() {
  return {
    export_id: ids.export,
    status: "queued",
    finished_at: null,
    artifact: null,
    downloads: [],
    error_code: null,
    error_message: null,
  }
}

// Keep every fixture assignable to the public discriminated union.
const _fixtureTypecheck: PlatformRevision[] = [xRevision, telegramRevision, instagramRevision, blogRevision]
void _fixtureTypecheck
