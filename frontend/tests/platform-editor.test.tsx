import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { PlatformEditor } from "@/features/packages/components/platform-editor"
import type {
  BlogRevision,
  CitationRef,
  InstagramRevision,
  XRevision,
} from "@/features/packages/types"
import { ApiError } from "@/lib/http"

const firstCitation: CitationRef = {
  evidenceSnapshotId: "snapshot-1",
  evidenceKey: "evidence:first",
  sourceUrl: "https://example.com/first",
  locator: "chars:0-12",
  excerptSha256: "a".repeat(64),
}

const secondCitation: CitationRef = {
  evidenceSnapshotId: "snapshot-2",
  evidenceKey: "evidence:second",
  sourceUrl: null,
  locator: "paragraph:2",
  excerptSha256: "b".repeat(64),
}

const instagramRevision: InstagramRevision = {
  id: "revision-instagram-2",
  platform: "instagram",
  variantId: "variant-instagram",
  contentPackId: "pack-1",
  storyId: "story-1",
  parentRevisionId: "revision-instagram-1",
  generationAttemptId: null,
  revisionNumber: 2,
  contentHash: "c".repeat(64),
  payload: {
    hook: "What changed?",
    caption: "A source-backed caption",
    cta: "Read the report",
    hashtags: ["#NewsCraft"],
    altText: "A summary card",
    carousel: [],
    citations: [firstCitation],
    manualChecklist: ["Verify the caption"],
  },
  validation: [
    {
      code: "instagram_caption_too_long",
      path: "caption",
      message: "Caption must be at most 2200 characters",
      severity: "error",
    },
  ],
  evidenceCitations: [firstCitation],
  manualChecklist: ["Verify the caption"],
  mediaPlan: [],
  sourceMedia: [],
  approvalState: "pending_review",
  validationResults: [],
  approvalNote: null,
  approvedAt: null,
  createdBy: "operator",
  origin: "operator",
  providerProfile: null,
  resolvedModel: null,
  promptVersion: null,
  createdAt: "2026-07-13T09:00:00Z",
}

const xRevision: XRevision = {
  ...instagramRevision,
  id: "revision-x-4",
  platform: "x",
  variantId: "variant-x",
  contentHash: "d".repeat(64),
  payload: {
    mode: "thread",
    posts: [
      { order: 1, text: "First post", media: [], citations: [firstCitation, firstCitation] },
      { order: 2, text: "Second post", media: [], citations: [secondCitation, firstCitation] },
    ],
    linkStrategy: "last_post",
    manualChecklist: ["Verify thread order"],
  },
  validation: [],
  evidenceCitations: [firstCitation, secondCitation],
  manualChecklist: ["Verify thread order"],
}

const blogRevision: BlogRevision = {
  ...instagramRevision,
  id: "revision-blog-3",
  platform: "blog",
  variantId: "variant-blog",
  contentHash: "f".repeat(64),
  payload: {
    title: "A grounded article",
    slug: "a-grounded-article",
    excerpt: "A concise source-backed summary.",
    bodyMarkdown: "## What happened\n\n" + "Grounded article text. ".repeat(12),
    headings: ["What happened"],
    citations: [secondCitation, firstCitation, secondCitation],
    tags: ["news"],
    seoDescription: "A complete search description grounded in the available reporting.",
    heroMedia: null,
    canonicalSources: ["https://example.com/first"],
    manualChecklist: ["Check canonical links"],
  },
  evidenceCitations: [secondCitation, firstCitation],
  manualChecklist: ["Check canonical links"],
  mediaPlan: [],
  validation: [],
}

it("creates an exact immutable Instagram edit request from the loaded revision", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<PlatformEditor revision={instagramRevision} onSave={onSave} />)

  expect(screen.getByLabelText("Caption")).toHaveAttribute("data-testid", "direction-boundary")
  expect(screen.getByLabelText("Caption")).toHaveAttribute("dir", "auto")
  expect(screen.getByLabelText("Alt text")).toHaveAttribute("dir", "auto")
  expect(screen.getByText("23/2200 characters")).toBeInTheDocument()
  expect(screen.getByText("Caption must be at most 2200 characters")).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Short caption" } })
  fireEvent.change(screen.getByLabelText("Edit note"), { target: { value: "Shorten the caption" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
  expect(onSave).toHaveBeenCalledWith({
    baseRevisionId: "revision-instagram-2",
    baseContentHash: "c".repeat(64),
    payload: {
      platform: "instagram",
      content: { ...instagramRevision.payload, caption: "Short caption" },
    },
    evidenceMap: [firstCitation],
    editNote: "Shorten the caption",
  })
  expect(screen.getByText("New pending review revision created")).toBeInTheDocument()
})

it("preserves complete citations in first-embedded order without duplicates", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<PlatformEditor revision={xRevision} onSave={onSave} />)

  fireEvent.change(screen.getByLabelText("Post 2"), { target: { value: "Updated second post" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
  expect(onSave.mock.calls[0][0].evidenceMap).toEqual([firstCitation, secondCitation])
  expect(onSave.mock.calls[0][0].payload).toEqual({
    platform: "x",
    content: {
      ...xRevision.payload,
      posts: [xRevision.payload.posts[0], { ...xRevision.payload.posts[1], text: "Updated second post" }],
    },
  })
})

it("builds the exact discriminated Blog request from edited content", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<PlatformEditor revision={blogRevision} onSave={onSave} />)

  fireEvent.change(screen.getByLabelText("Blog title"), { target: { value: "Updated grounded article" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
  expect(onSave).toHaveBeenCalledWith({
    baseRevisionId: "revision-blog-3",
    baseContentHash: "f".repeat(64),
    payload: {
      platform: "blog",
      content: { ...blogRevision.payload, title: "Updated grounded article" },
    },
    evidenceMap: [secondCitation, firstCitation],
    editNote: "Operator edit",
  })
})

it("keeps rejected citation-integrity edits local and unsaved", async () => {
  const onSave = vi.fn().mockRejectedValue(
    new ApiError(
      "Unprocessable Entity",
      422,
      JSON.stringify({ detail: "Edited claims must retain their complete evidence citations" }),
    ),
  )
  render(<PlatformEditor revision={instagramRevision} onSave={onSave} />)

  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Locally edited claim" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))

  expect(await screen.findByText("Edited claims must retain their complete evidence citations")).toBeInTheDocument()
  expect(screen.getByLabelText("Caption")).toHaveValue("Locally edited claim")
  expect(screen.queryByText("New pending review revision created")).not.toBeInTheDocument()
})

it("keeps local text and citation errors visible through a stale reload", async () => {
  const onSave = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, "revision changed"))
  const onReload = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(
    <PlatformEditor revision={instagramRevision} onSave={onSave} onReload={onReload} />,
  )

  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Operator local text" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  expect(await screen.findByText("A newer revision exists. Reload the latest revision before saving."))
    .toBeInTheDocument()
  expect(screen.getByLabelText("Caption")).toHaveValue("Operator local text")
  expect(screen.getByText("Caption must be at most 2200 characters")).toBeInTheDocument()
  expect(screen.queryByText("New pending review revision created")).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole("button", { name: "Reload latest" }))
  await waitFor(() => expect(onReload).toHaveBeenCalledTimes(1))
  rerender(
    <PlatformEditor
      revision={{
        ...instagramRevision,
        id: "revision-instagram-3",
        contentHash: "e".repeat(64),
        payload: { ...instagramRevision.payload, caption: "Server text" },
      }}
      onSave={onSave}
      onReload={onReload}
    />,
  )
  expect(screen.getByLabelText("Caption")).toHaveValue("Operator local text")
  expect(screen.getByText("Caption must be at most 2200 characters")).toBeInTheDocument()
})

it("reports dirty state so approval controls can stay fenced", () => {
  const onDirtyChange = vi.fn()
  render(<PlatformEditor revision={instagramRevision} onSave={vi.fn()} onDirtyChange={onDirtyChange} />)

  expect(onDirtyChange).toHaveBeenLastCalledWith(false)
  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Unsaved operator copy" } })
  expect(onDirtyChange).toHaveBeenLastCalledWith(true)
})

it("keeps approval fenced after saving until the new revision is actually loaded", async () => {
  const onDirtyChange = vi.fn()
  const onSave = vi.fn().mockResolvedValue({
    ...instagramRevision,
    id: "revision-instagram-3",
    contentHash: "9".repeat(64),
  })
  const view = render(
    <PlatformEditor revision={instagramRevision} onSave={onSave} onDirtyChange={onDirtyChange} />,
  )

  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Saved child copy" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  await screen.findByText("New pending review revision created")
  expect(onDirtyChange).toHaveBeenLastCalledWith(true)
  expect(screen.getByRole("button", { name: "Save new revision" })).toBeDisabled()
  expect(screen.getByLabelText("Caption")).toBeDisabled()

  view.rerender(
    <PlatformEditor
      revision={{
        ...instagramRevision,
        id: "revision-instagram-3",
        contentHash: "9".repeat(64),
        payload: { ...instagramRevision.payload, caption: "Saved child copy" },
      }}
      onSave={onSave}
      onDirtyChange={onDirtyChange}
    />,
  )
  await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false))
  expect(screen.getByLabelText("Caption")).toBeEnabled()
})

it("does not leave the loaded child fenced when it arrives before save resolves", async () => {
  const child = {
    ...instagramRevision,
    id: "revision-instagram-3",
    contentHash: "8".repeat(64),
    payload: { ...instagramRevision.payload, caption: "First saved child copy" },
  }
  let rerender: ReturnType<typeof render>["rerender"]
  const onSave = vi.fn(async () => {
    rerender(<PlatformEditor revision={child} onSave={onSave} />)
    await Promise.resolve()
    return child
  })
  const view = render(<PlatformEditor revision={instagramRevision} onSave={onSave} />)
  rerender = view.rerender

  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "First saved child copy" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  await screen.findByText("New pending review revision created")
  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "A second child edit" } })

  expect(screen.getByRole("button", { name: "Save new revision" })).toBeEnabled()
})

it("switches platform discriminators without rendering the previous payload shape", () => {
  const view = render(<PlatformEditor revision={instagramRevision} onSave={vi.fn()} />)

  expect(screen.getByLabelText("Caption")).toHaveValue(instagramRevision.payload.caption)
  expect(() => view.rerender(<PlatformEditor revision={xRevision} onSave={vi.fn()} />)).not.toThrow()
  expect(screen.getByLabelText("Post 1")).toHaveValue("First post")
  expect(screen.queryByLabelText("Caption")).not.toBeInTheDocument()
})

it("loads a normally selected same-platform revision instead of carrying local copy across identities", () => {
  const view = render(<PlatformEditor revision={instagramRevision} onSave={vi.fn()} />)
  fireEvent.change(screen.getByLabelText("Caption"), { target: { value: "Unsaved revision two copy" } })

  view.rerender(
    <PlatformEditor
      revision={{
        ...instagramRevision,
        id: "revision-instagram-8",
        contentHash: "7".repeat(64),
        payload: { ...instagramRevision.payload, caption: "Exact revision eight copy" },
      }}
      onSave={vi.fn()}
    />,
  )

  expect(screen.getByLabelText("Caption")).toHaveValue("Exact revision eight copy")
})

it("keeps Telegram on its compatible edit callback", async () => {
  const onTelegramSave = vi.fn().mockResolvedValue(undefined)
  render(
    <PlatformEditor
      revision={{
        ...instagramRevision,
        id: "revision-telegram-2",
        platform: "telegram",
        variantId: "variant-telegram",
        payload: {
          body: "Grounded Telegram copy",
          parseMode: "HTML",
          buttons: [],
          sourceItemId: null,
          sourceUrl: null,
          mediaPolicy: "preserve",
          mediaAssetIds: [],
          direction: "ltr",
          dryRun: false,
        },
        validation: [],
        evidenceCitations: [firstCitation],
        manualChecklist: [],
        mediaPlan: [],
      }}
      onTelegramSave={onTelegramSave}
    />,
  )

  expect(screen.getByLabelText("Telegram message")).toHaveAttribute("data-testid", "direction-boundary")
  expect(screen.getByLabelText("Telegram message")).toHaveAttribute("dir", "ltr")
  fireEvent.change(screen.getByLabelText("Telegram message"), { target: { value: "Edited Telegram copy" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  await waitFor(() => expect(onTelegramSave).toHaveBeenCalledTimes(1))
  expect(onTelegramSave).toHaveBeenCalledWith({
    variantId: "variant-telegram",
    baseRevisionId: "revision-telegram-2",
    baseContentHash: "c".repeat(64),
    content: { body: "Edited Telegram copy", parseMode: "HTML", buttons: [] },
    mediaAssetIds: [],
    editNote: "Operator edit",
  })
})
