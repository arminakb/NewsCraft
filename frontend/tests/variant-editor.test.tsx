import { render, screen } from "@testing-library/react"
import { fireEvent } from "@testing-library/react"

import { VariantEditor } from "@/components/editorial/variant-editor"
import type { VariantRevision } from "@/features/editorial/types"
import { ApiError } from "@/lib/http"

const revision: VariantRevision = {
  id: "rev-2", variantId: "variant-1", contentPackId: "pack-1", storyId: "story-1", parentRevisionId: "rev-1", generationAttemptId: null,
  revisionNumber: 2, content: { body: "Draft", parseMode: "HTML", buttons: [], mediaAssetIds: [], sourceUrl: null, mediaPolicy: "preserve", direction: "ltr", dryRun: false },
  contentHash: "a".repeat(64), evidenceMap: [{ evidenceSnapshotId: "e1", evidenceKey: "source-1", sourceUrl: null, locator: "chars:0-5", excerptSha256: "b".repeat(64) }],
  validationResults: [], approvalState: "pending_review", approvalNote: null, approvedAt: null, createdBy: "operator", origin: "operator", createdAt: "2026-07-12T08:00:00Z", providerProfile: null, resolvedModel: null,
}

it("uses the persisted Telegram direction through the shared content boundary", () => {
  render(<VariantEditor revision={{ ...revision, content: { ...revision.content, body: "متن", direction: "rtl" } }} />)

  expect(screen.getByLabelText("Telegram message")).toHaveAttribute("data-testid", "direction-boundary")
  expect(screen.getByLabelText("Telegram message")).toHaveAttribute("dir", "rtl")
  expect(screen.getByLabelText("Telegram message")).not.toHaveAttribute("lang")
})

it("uses automatic direction for Telegram labels and operator prose without affecting URLs", () => {
  render(
    <VariantEditor
      revision={{
        ...revision,
        content: {
          ...revision.content,
          buttons: [{ text: "منبع خبر", url: "https://example.com" }],
        },
      }}
      availableProviders={[{
        id: "provider-uuid",
        name: "Codex CLI",
        providerType: "codex",
        defaultModel: "gpt-5.4",
        capabilities: { generation: true, research: true },
        unavailableReason: null,
      }]}
    />
  )

  for (const field of [
    screen.getByLabelText("Button 1 text"),
    screen.getByLabelText("Edit note"),
    screen.getByLabelText("Rejection reason"),
    screen.getByLabelText("Regeneration instruction"),
  ]) {
    expect(field).toHaveAttribute("data-testid", "direction-boundary")
    expect(field).toHaveAttribute("dir", "auto")
    expect(field).not.toHaveAttribute("lang")
  }
  expect(screen.getByLabelText("Button 1 URL")).not.toHaveAttribute("data-testid")
})

it("approves the exact loaded revision and hash", () => {
  const approve = vi.fn().mockResolvedValue({ ...revision, approvalState: "approved" })
  render(<VariantEditor revision={revision} onApprove={approve} />)
  fireEvent.click(screen.getByRole("button", { name: "Approve revision" }))
  expect(approve).toHaveBeenCalledWith({ revisionId: "rev-2", expectedContentHash: "a".repeat(64), note: null })
})

it("handles a stale save without discarding operator edits", async () => {
  const save = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, "revision changed"))
  render(<VariantEditor revision={{ ...revision, approvalState: "approved" }} onSave={save} />)
  fireEvent.change(screen.getByLabelText("Telegram message"), { target: { value: "Draft Added context" } })
  expect(screen.getByText("Changes will create a pending review revision")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  expect(await screen.findByText("A newer revision exists. Reload before saving.")).toBeInTheDocument()
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Draft Added context")
})

it("submits the provider while the backend resolves the active prompt", () => {
  const regenerate = vi.fn().mockResolvedValue({ jobId: "job-1", status: "queued", deduplicated: false })
  render(<VariantEditor revision={revision} availableProviders={[{ id: "provider-uuid", name: "Codex CLI", providerType: "codex", defaultModel: "gpt-5.4", capabilities: { generation: true, research: true }, unavailableReason: null }]} onRegenerate={regenerate} />)
  fireEvent.change(screen.getByLabelText("AI provider"), { target: { value: "provider-uuid" } })
  fireEvent.click(screen.getByRole("button", { name: "Regenerate" }))
  expect(regenerate).toHaveBeenCalledWith({ variantId: "variant-1", providerProfileId: "provider-uuid", instruction: null })
  expect(screen.getByText(/active Telegram prompt is resolved/i)).toBeInTheDocument()
})

it("cannot approve a revision with a failed persisted media gate even after a forced click", () => {
  const approve = vi.fn()
  render(<VariantEditor revision={{ ...revision, validationResults: [{ gate: "media", ok: false, reason: "Missing verified media" }] }} onApprove={approve} />)
  const button = screen.getByRole("button", { name: "Approve revision" })
  expect(button).toBeDisabled()
  fireEvent.click(button)
  expect(approve).not.toHaveBeenCalled()
  expect(screen.getByText(/Missing verified media/)).toBeInTheDocument()
})

it("reloads a conflict and reapplies the complete editable draft exactly once", async () => {
  const save = vi.fn().mockRejectedValueOnce(new ApiError("Conflict", 409, "changed"))
  const reload = vi.fn()
  const { rerender } = render(<VariantEditor revision={revision} onSave={save} onReload={reload} />)
  fireEvent.change(screen.getByLabelText("Telegram message"), { target: { value: "Operator draft" } })
  fireEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  await screen.findByText("A newer revision exists. Reload before saving.")
  fireEvent.click(screen.getByRole("button", { name: "Reload latest" }))
  expect(reload).toHaveBeenCalledTimes(1)
  rerender(<VariantEditor revision={{ ...revision, id: "rev-3", revisionNumber: 3, contentHash: "c".repeat(64), content: { ...revision.content, body: "Server draft" } }} onSave={save} onReload={reload} />)
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Server draft")
  fireEvent.click(screen.getByRole("button", { name: "Reapply my edits" }))
  expect(screen.getByLabelText("Telegram message")).toHaveValue("Operator draft")
  expect(screen.queryByRole("button", { name: "Reapply my edits" })).not.toBeInTheDocument()
})

it("reports button and media assignment changes as dirty", () => {
  const onDirtyChange = vi.fn()
  render(<VariantEditor revision={{ ...revision, content: { ...revision.content, buttons: [{ text: "Source", url: "https://example.com" }], mediaAssetIds: ["media-1"] } }} onDirtyChange={onDirtyChange} />)
  fireEvent.change(screen.getByLabelText("Button 1 text"), { target: { value: "Updated source" } })
  expect(onDirtyChange).toHaveBeenLastCalledWith(true)
  fireEvent.change(screen.getByLabelText("Media asset assignments"), { target: { value: "media-2" } })
  expect(onDirtyChange).toHaveBeenLastCalledWith(true)
})
