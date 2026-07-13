import { fireEvent, render, screen } from "@testing-library/react"

import { MediaPlan } from "@/features/packages/components/media-plan"
import type { InstagramPlatformRevision, XPlatformRevision } from "@/features/packages/types"

const revision: InstagramPlatformRevision = {
  id: "revision-instagram-2",
  platform: "instagram",
  variantId: "variant-instagram",
  contentPackId: "pack-1",
  storyId: "story-1",
  parentRevisionId: "revision-instagram-1",
  generationAttemptId: null,
  revisionNumber: 2,
  contentHash: "a".repeat(64),
  payload: {
    hook: "A grounded carousel",
    caption: "Caption",
    cta: "Read more",
    hashtags: [],
    altText: "Carousel summary",
    carousel: [
      {
        order: 1,
        headline: "First",
        body: "First slide",
        media: {
          mediaAssetId: "asset-1",
          role: "slide",
          order: 1,
          altText: "First source image",
          manualBrief: null,
          imagePrompt: "Crop the verified source image",
        },
      },
      {
        order: 2,
        headline: "Second",
        body: "Second slide",
        media: {
          mediaAssetId: null,
          role: "slide",
          order: 2,
          altText: "A manually created fact card",
          manualBrief: "Create a source-grounded card manually",
          imagePrompt: null,
        },
      },
    ],
    citations: [],
    manualChecklist: ["Verify carousel order"],
  },
  validation: [],
  evidenceCitations: [],
  manualChecklist: ["Verify carousel order"],
  mediaPlan: [],
  sourceMedia: [
    {
      id: "asset-1",
      kind: "image",
      mimeType: "image/jpeg",
      width: 1600,
      height: 900,
      durationSeconds: null,
      byteLength: 320000,
      checksumSha256: "b".repeat(64),
      fetchStatus: "downloaded",
      available: true,
      role: "source",
      order: 1,
    },
    {
      id: "asset-2",
      kind: "video",
      mimeType: "video/mp4",
      width: 1080,
      height: 1920,
      durationSeconds: "18.4",
      byteLength: 640000,
      checksumSha256: null,
      fetchStatus: "failed",
      available: false,
      role: "source",
      order: 2,
    },
  ],
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

it("shows ordered source assets, availability, assignments, and manual requirements", () => {
  render(<MediaPlan revision={revision} />)

  const assets = screen.getAllByRole("listitem", { name: /Source asset/ })
  expect(assets[0]).toHaveTextContent("asset-1")
  expect(assets[0]).toHaveTextContent("image/jpeg")
  expect(assets[0]).toHaveTextContent("1600×900")
  expect(assets[0]).toHaveTextContent("Available")
  expect(assets[1]).toHaveTextContent("asset-2")
  expect(assets[1]).toHaveTextContent("Unavailable")
  expect(screen.getByText("First source image")).toBeInTheDocument()
  expect(screen.getByText("Crop the verified source image")).toBeInTheDocument()
  expect(screen.getByText("Required manual asset")).toBeInTheDocument()
  expect(screen.getByText("Create a source-grounded card manually")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Move slide/ })).not.toBeInTheDocument()
})

it("reorders assignments by emitting a new immutable payload", () => {
  const onReorder = vi.fn()
  render(<MediaPlan revision={revision} onReorder={onReorder} />)

  const moveSecondUp = screen.getByRole("button", { name: "Move slide 2 up" })
  expect(moveSecondUp).toHaveAccessibleName("Move slide 2 up")
  fireEvent.click(moveSecondUp)

  expect(onReorder).toHaveBeenCalledTimes(1)
  expect(onReorder).toHaveBeenCalledWith({
    ...revision.payload,
    carousel: [
      {
        ...revision.payload.carousel[1],
        order: 1,
        media: { ...revision.payload.carousel[1].media, order: 1 },
      },
      {
        ...revision.payload.carousel[0],
        order: 2,
        media: { ...revision.payload.carousel[0].media, order: 2 },
      },
    ],
  })
  expect(revision.payload.carousel[0].headline).toBe("First")
})

it("renders X media assignments in their declared order", () => {
  const first = {
    mediaAssetId: "asset-1",
    role: "post" as const,
    order: 1,
    altText: "First assignment",
    manualBrief: null,
    imagePrompt: null,
  }
  const second = {
    mediaAssetId: "asset-2",
    role: "post" as const,
    order: 2,
    altText: "Second assignment",
    manualBrief: "Replace unavailable video manually",
    imagePrompt: null,
  }
  const xRevision: XPlatformRevision = {
    ...revision,
    platform: "x",
    payload: {
      mode: "single",
      posts: [{ order: 1, text: "A grounded post", media: [second, first], citations: [] }],
      linkStrategy: "no_link",
      manualChecklist: ["Verify post media"],
    },
    manualChecklist: ["Verify post media"],
    mediaPlan: [second, first],
  }

  render(<MediaPlan revision={xRevision} />)
  const assignments = screen.getAllByRole("listitem", { name: /Media assignment post/ })
  expect(assignments[0]).toHaveTextContent("asset-1")
  expect(assignments[1]).toHaveTextContent("asset-2")
})

it("marks each X post with missing media as a required manual assignment", () => {
  const assigned = revision.payload.carousel[0].media
  const xRevision: XPlatformRevision = {
    ...revision,
    platform: "x",
    payload: {
      mode: "thread",
      posts: [
        { order: 1, text: "Post with media", media: [{ ...assigned, role: "post" }], citations: [] },
        { order: 2, text: "Post needing media", media: [], citations: [] },
      ],
      linkStrategy: "no_link",
      manualChecklist: ["Verify post media"],
    },
    manualChecklist: ["Verify post media"],
    mediaPlan: [{ ...assigned, role: "post" }],
  }

  render(<MediaPlan revision={xRevision} />)
  expect(screen.getByText(/Post 2 has no assigned media/)).toBeInTheDocument()
  expect(screen.getAllByText("Required manual asset")).toHaveLength(1)
})

it("marks unavailable Telegram media and unsupported manual-platform media explicitly", () => {
  const telegramRevision = {
    ...revision,
    id: "revision-telegram-1",
    platform: "telegram" as const,
    variantId: "variant-telegram",
    payload: {
      body: "Grounded Telegram post",
      parseMode: "HTML" as const,
      buttons: [],
      sourceItemId: null,
      sourceUrl: null,
      mediaPolicy: "preserve" as const,
      mediaAssetIds: ["asset-2"],
      direction: "ltr" as const,
      dryRun: false,
    },
    evidenceCitations: [],
    manualChecklist: [],
    mediaPlan: ["asset-2"],
  }
  const unsupported = {
    id: "asset-3",
    kind: "document",
    mimeType: "application/pdf",
    width: null,
    height: null,
    durationSeconds: null,
    byteLength: 24000,
    checksumSha256: "c".repeat(64),
    fetchStatus: "downloaded",
    available: true,
    role: "source",
    order: 3,
  }
  const unsupportedRevision: InstagramPlatformRevision = {
    ...revision,
    payload: {
      ...revision.payload,
      carousel: [{
        ...revision.payload.carousel[0],
        media: { ...revision.payload.carousel[0].media, mediaAssetId: "asset-3" },
      }],
    },
    sourceMedia: [...revision.sourceMedia, unsupported],
  }

  const view = render(<MediaPlan revision={telegramRevision} />)
  expect(screen.getByText(/Telegram item 1 requires a manual replacement/)).toBeInTheDocument()
  view.rerender(<MediaPlan revision={unsupportedRevision} />)
  expect(screen.getByText(/assigned source type is unsupported/)).toBeInTheDocument()
})

it("does not invent manual Telegram work for an intentional no-media policy", () => {
  const telegramRevision = {
    ...revision,
    id: "revision-telegram-omit",
    platform: "telegram" as const,
    variantId: "variant-telegram",
    payload: {
      body: "Message-only Telegram post",
      parseMode: "HTML" as const,
      buttons: [],
      sourceItemId: null,
      sourceUrl: null,
      mediaPolicy: "omit" as const,
      mediaAssetIds: [],
      direction: "ltr" as const,
      dryRun: false,
    },
    evidenceCitations: [],
    manualChecklist: [],
    mediaPlan: [],
  }
  const view = render(<MediaPlan revision={telegramRevision} />)
  expect(screen.queryByText("Required manual asset")).not.toBeInTheDocument()
  expect(screen.getByText(/message-only publish/)).toBeInTheDocument()

  view.rerender(
    <MediaPlan
      revision={{
        ...telegramRevision,
        id: "revision-telegram-omit-with-id",
        payload: { ...telegramRevision.payload, mediaAssetIds: ["asset-2"] },
        mediaPlan: ["asset-2"],
      }}
    />,
  )
  expect(screen.queryByText("Required manual asset")).not.toBeInTheDocument()
  expect(screen.getByText(/message-only publish/)).toBeInTheDocument()

  view.rerender(
    <MediaPlan
      revision={{
        ...telegramRevision,
        id: "revision-telegram-manual",
        payload: { ...telegramRevision.payload, mediaPolicy: "replace_manually", mediaAssetIds: ["asset-1"] },
        mediaPlan: ["asset-1"],
      }}
    />,
  )
  expect(screen.getByText("Required manual asset")).toBeInTheDocument()
})

it("flags a mixed Telegram document and visual plan for manual review", () => {
  const document = {
    id: "asset-document",
    kind: "document",
    mimeType: "application/pdf",
    width: null,
    height: null,
    durationSeconds: null,
    byteLength: 24000,
    checksumSha256: "d".repeat(64),
    fetchStatus: "downloaded",
    available: true,
    role: "source",
    order: 3,
  }
  const telegramRevision = {
    ...revision,
    id: "revision-telegram-mixed",
    platform: "telegram" as const,
    variantId: "variant-telegram",
    payload: {
      body: "Telegram post with mixed media",
      parseMode: "HTML" as const,
      buttons: [],
      sourceItemId: null,
      sourceUrl: null,
      mediaPolicy: "preserve" as const,
      mediaAssetIds: ["asset-1", "asset-document"],
      direction: "ltr" as const,
      dryRun: false,
    },
    evidenceCitations: [],
    manualChecklist: [],
    mediaPlan: ["asset-1", "asset-document"],
    sourceMedia: [...revision.sourceMedia, document],
  }

  render(<MediaPlan revision={telegramRevision} />)
  expect(screen.getByText(/Mixed Telegram documents and visual media require manual review/)).toBeInTheDocument()
})

it("provides labelled keyboard-operable move controls", () => {
  const onReorder = vi.fn()
  render(<MediaPlan revision={revision} onReorder={onReorder} />)

  const moveFirstDown = screen.getByRole("button", { name: "Move slide 1 down" })
  moveFirstDown.focus()
  fireEvent.keyDown(moveFirstDown, { key: "Enter" })
  fireEvent.click(moveFirstDown)
  expect(moveFirstDown).toHaveFocus()
  expect(onReorder).toHaveBeenCalledTimes(1)
  expect(screen.getByRole("button", { name: "Move slide 1 up" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "Move slide 2 down" })).toBeDisabled()
})
