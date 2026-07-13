import { render, screen } from "@testing-library/react"
import { RevisionTimeline } from "@/components/editorial/revision-timeline"
import type { VariantRevision } from "@/lib/editorial-types"

it("renders immutable revision ancestry and validation", () => {
  const revisions = [{ id: "rev-2", variantId: "v1", contentPackId: "pack-1", storyId: "story-1", parentRevisionId: "rev-1", generationAttemptId: null, revisionNumber: 2, content: { body: "body", parseMode: "HTML", buttons: [], mediaAssetIds: [], sourceUrl: null, mediaPolicy: "preserve", direction: "ltr", dryRun: false }, contentHash: "a".repeat(64), evidenceMap: [], validationResults: [{ gate: "citations", ok: true, reason: null }], approvalState: "pending_review", approvalNote: null, approvedAt: null, createdBy: "operator", origin: "operator", createdAt: "2026-07-12T08:00:00Z", providerProfile: null, resolvedModel: null }] satisfies VariantRevision[]
  render(<RevisionTimeline revisions={revisions} activeRevisionId="rev-2" />)
  expect(screen.getByText("Revision 2")).toBeInTheDocument()
  expect(screen.getByText(/Parent rev-1/)).toBeInTheDocument()
  expect(screen.getByText("citations: passed")).toBeInTheDocument()
})

it("renders typed platform validation issues without requiring Telegram fields", () => {
  const revisions = [{
    id: "rev-instagram-2",
    revisionNumber: 2,
    parentRevisionId: "rev-instagram-1",
    approvalState: "pending_review",
    origin: "operator",
    createdBy: "operator",
    createdAt: "2026-07-13T08:00:00Z",
    providerProfile: null,
    resolvedModel: null,
    validation: [{ code: "instagram_caption_too_long", path: "caption", message: "Caption exceeds the platform limit", severity: "error" }],
  }]

  render(<RevisionTimeline revisions={revisions} activeRevisionId="rev-instagram-2" />)

  expect(screen.getByText("instagram_caption_too_long: Caption exceeds the platform limit")).toBeInTheDocument()
})
