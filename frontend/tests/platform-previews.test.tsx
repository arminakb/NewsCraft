import { render, screen, within } from "@testing-library/react"

import { PlatformPreview } from "@/features/packages/components/platform-preview"
import type {
  BlogRevision,
  InstagramRevision,
  PlatformRevision,
  TelegramRevision,
  XRevision,
} from "@/features/packages/types"

const revisionMetadata = {
  id: "91111111-1111-4111-8111-111111111111",
  variantId: "92111111-1111-4111-8111-111111111111",
  contentPackId: "93111111-1111-4111-8111-111111111111",
  storyId: "94111111-1111-4111-8111-111111111111",
  parentRevisionId: null,
  generationAttemptId: null,
  revisionNumber: 1,
  contentHash: "c".repeat(64),
  validationResults: [],
  approvalState: "pending_review" as const,
  approvalNote: null,
  approvedAt: null,
  createdBy: "generation",
  origin: "generation" as const,
  providerProfile: null,
  resolvedModel: null,
  promptVersion: null,
  createdAt: "2026-07-13T08:00:00Z",
}

const linkedCitation = {
  evidenceSnapshotId: "11111111-1111-4111-8111-111111111111",
  evidenceKey: "evidence:public-report",
  sourceUrl: "https://example.com/public-report",
  locator: "chars:0-42",
  excerptSha256: "a".repeat(64),
}

const operatorCitation = {
  evidenceSnapshotId: "22222222-2222-4222-8222-222222222222",
  evidenceKey: "operator:desk-note",
  sourceUrl: null,
  locator: "chars:4-28",
  excerptSha256: "b".repeat(64),
}

const telegramRevision = {
  ...revisionMetadata,
  platform: "telegram",
  payload: {
    body: "<strong>Exact Telegram dispatch copy</strong>",
    parseMode: "HTML",
    buttons: [{ text: "Read the report", url: linkedCitation.sourceUrl }],
    sourceItemId: null,
    sourceUrl: null,
    mediaPolicy: "replace_manually",
    mediaAssetIds: ["31111111-1111-4111-8111-111111111111"],
    direction: "rtl",
    dryRun: false,
  },
  validation: [],
  evidenceCitations: [linkedCitation, operatorCitation],
  manualChecklist: ["Adjacent operator check"],
  mediaPlan: ["31111111-1111-4111-8111-111111111111"],
  sourceMedia: [],
} satisfies TelegramRevision

const instagramRevision = {
  ...revisionMetadata,
  platform: "instagram",
  payload: {
    hook: "Grounded Instagram hook",
    caption: "Grounded Instagram caption",
    cta: "Read the cited report",
    hashtags: ["#NewsCraft", "#Grounded"],
    altText: "Two grounded carousel slides",
    carousel: [
      {
        order: 2,
        headline: "Second slide",
        body: "Second slide body",
        media: {
          mediaAssetId: null,
          role: "slide",
          order: 2,
          altText: "Diagram still required for the second slide",
          manualBrief: "Create a sourced comparison diagram",
          imagePrompt: "A neutral two-column comparison",
        },
      },
      {
        order: 1,
        headline: "First slide",
        body: "First slide body",
        media: {
          mediaAssetId: "41111111-1111-4111-8111-111111111111",
          role: "slide",
          order: 1,
          altText: "The cited report cover",
          manualBrief: null,
          imagePrompt: null,
        },
      },
    ],
    citations: [linkedCitation, operatorCitation],
    manualChecklist: ["Verify carousel order"],
  },
  validation: [],
  evidenceCitations: [linkedCitation, operatorCitation],
  manualChecklist: ["Verify carousel order"],
  mediaPlan: [],
  sourceMedia: [],
} satisfies InstagramRevision

const xRevision = {
  ...revisionMetadata,
  platform: "x",
  payload: {
    mode: "thread",
    posts: [
      {
        order: 2,
        text: "Second exact post",
        media: [{
          mediaAssetId: null,
          role: "post",
          order: 1,
          altText: "Manual chart for the second post",
          manualBrief: "Build the chart from cited numbers",
          imagePrompt: null,
        }],
        citations: [operatorCitation],
      },
      {
        order: 1,
        text: "First exact post",
        media: [],
        citations: [linkedCitation],
      },
    ],
    linkStrategy: "last_post",
    manualChecklist: ["Recheck X character weighting"],
  },
  validation: [],
  evidenceCitations: [linkedCitation, operatorCitation],
  manualChecklist: ["Recheck X character weighting"],
  mediaPlan: [],
  sourceMedia: [],
} satisfies XRevision

const blogRevision = {
  ...revisionMetadata,
  platform: "blog",
  payload: {
    title: "Grounded blog title",
    slug: "grounded-blog-title",
    excerpt: "A concise grounded excerpt.",
    bodyMarkdown: "## What happened\n\nThe exact grounded article body.",
    headings: ["What happened", "Why it matters"],
    citations: [linkedCitation, operatorCitation],
    tags: ["news", "research"],
    seoDescription: "A grounded search description that reports only cited facts and context.",
    heroMedia: {
      mediaAssetId: null,
      role: "hero",
      order: 1,
      altText: "A manually produced grounded hero image",
      manualBrief: "Create the hero from the cited report cover",
      imagePrompt: "Editorial report cover on a neutral background",
    },
    canonicalSources: [linkedCitation.sourceUrl],
    manualChecklist: ["Verify canonical source links"],
  },
  validation: [],
  evidenceCitations: [linkedCitation, operatorCitation],
  manualChecklist: ["Verify canonical source links"],
  mediaPlan: [],
  sourceMedia: [],
} satisfies BlogRevision

it.each([
  ["telegram", telegramRevision, "Telegram preview"],
  ["instagram", instagramRevision, "Instagram preview"],
  ["x", xRevision, "X thread preview"],
  ["blog", blogRevision, "Blog preview"],
])("renders the truthful %s approximation region", (_platform, revision, label) => {
  render(<PlatformPreview revision={revision} />)

  const preview = screen.getByRole("region", { name: label })
  expect(preview).toHaveTextContent(/approximation only/i)
  expect(preview).toHaveTextContent(/not pixel parity or live platform state/i)
})

it("keeps Telegram's exact nine content fields separate from adjacent evidence and checklist projections", () => {
  const originalPayload = structuredClone(telegramRevision.payload)
  render(<PlatformPreview revision={telegramRevision} />)

  const payload = screen.getByRole("region", { name: "Exact Telegram payload" })
  const evidence = screen.getByRole("region", { name: "Telegram evidence citations" })
  const checklist = screen.getByRole("region", { name: "Telegram manual checklist" })

  expect(payload).toHaveTextContent("<strong>Exact Telegram dispatch copy</strong>")
  expect(payload).toHaveTextContent("replace_manually")
  expect(payload).toHaveTextContent("31111111-1111-4111-8111-111111111111")
  expect(payload).not.toHaveTextContent(linkedCitation.evidenceKey)
  expect(payload).not.toHaveTextContent("Adjacent operator check")
  expect(evidence).toHaveTextContent(linkedCitation.evidenceKey)
  expect(checklist).toHaveTextContent("Adjacent operator check")
  expect(telegramRevision.payload).toEqual(originalPayload)
  expect(Object.keys(telegramRevision.payload)).toEqual([
    "body", "parseMode", "buttons", "sourceItemId", "sourceUrl",
    "mediaPolicy", "mediaAssetIds", "direction", "dryRun",
  ])
})

it("renders Instagram copy and carousel media in declared order, including a required manual asset", () => {
  render(<PlatformPreview revision={instagramRevision} />)
  const preview = screen.getByRole("region", { name: "Instagram preview" })

  expect(preview).toHaveTextContent("Grounded Instagram hook")
  expect(preview).toHaveTextContent("Grounded Instagram caption")
  expect(preview).toHaveTextContent("Two grounded carousel slides")
  const previewText = preview.textContent ?? ""
  expect(previewText.indexOf("First slide")).toBeLessThan(previewText.indexOf("Second slide"))
  expect(within(preview).getByRole("article", { name: "Media assignment 2" })).toHaveTextContent("Manual media required")
  expect(preview).toHaveTextContent("Diagram still required for the second slide")
  expect(preview).toHaveTextContent("Create a sourced comparison diagram")
})

it("renders X posts in declared order with per-post citations and media gaps", () => {
  render(<PlatformPreview revision={xRevision} />)
  const preview = screen.getByRole("region", { name: "X thread preview" })

  const previewText = preview.textContent ?? ""
  expect(previewText.indexOf("First exact post")).toBeLessThan(previewText.indexOf("Second exact post"))
  expect(preview).toHaveTextContent("last post")
  expect(preview).toHaveTextContent("Manual chart for the second post")
  expect(within(preview).getByRole("article", { name: "Media assignment 1" })).toHaveTextContent("Manual media required")
})

it("renders the complete blog package and truthful manual hero state", () => {
  render(<PlatformPreview revision={blogRevision} />)
  const preview = screen.getByRole("region", { name: "Blog preview" })

  expect(preview).toHaveTextContent("Grounded blog title")
  expect(preview).toHaveTextContent("grounded-blog-title")
  expect(preview).toHaveTextContent("The exact grounded article body.")
  expect(preview).toHaveTextContent("Why it matters")
  expect(preview).toHaveTextContent("news")
  expect(preview).toHaveTextContent("research")
  expect(preview).toHaveTextContent("A manually produced grounded hero image")
  expect(within(preview).getByRole("article", { name: "Media assignment 1" })).toHaveTextContent("Manual media required")
})

it("renders every citation field and never invents a link for operator-provided evidence", () => {
  render(<PlatformPreview revision={instagramRevision} />)

  const linked = screen.getByRole("article", { name: "Citation 1" })
  expect(linked).toHaveTextContent(linkedCitation.evidenceSnapshotId)
  expect(linked).toHaveTextContent(linkedCitation.evidenceKey)
  expect(linked).toHaveTextContent(linkedCitation.locator)
  expect(linked).toHaveTextContent(linkedCitation.excerptSha256)
  expect(within(linked).getByRole("link", { name: linkedCitation.sourceUrl })).toHaveAttribute("href", linkedCitation.sourceUrl)

  const operatorProvided = screen.getByRole("article", { name: "Citation 2" })
  expect(operatorProvided).toHaveTextContent(operatorCitation.evidenceSnapshotId)
  expect(operatorProvided).toHaveTextContent(operatorCitation.evidenceKey)
  expect(operatorProvided).toHaveTextContent(operatorCitation.locator)
  expect(operatorProvided).toHaveTextContent(operatorCitation.excerptSha256)
  expect(operatorProvided).toHaveTextContent("Operator-provided evidence — no source link")
  expect(within(operatorProvided).queryByRole("link")).not.toBeInTheDocument()
})

it("fails closed when an unsupported platform reaches the exhaustive dispatcher", () => {
  const unsupported = { ...telegramRevision, platform: "mastodon" } as unknown as PlatformRevision

  expect(() => render(<PlatformPreview revision={unsupported} />)).toThrow(/Unsupported platform preview/)
})
