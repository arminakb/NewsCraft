import { render, screen } from "@testing-library/react"
import { EvidencePanel } from "@/components/editorial/evidence-panel"

const evidence = { id: "e1", evidenceKey: "source-1", title: "Release", contentText: "Team announced on July 11 in public.", contentSha256: "a".repeat(64), sourceUrl: "https://example.com/release", authors: [], publishedAt: null, capturedAt: "2026-07-12T08:00:00Z" }
const citation = { evidenceSnapshotId: "e1", evidenceKey: "source-1", sourceUrl: evidence.sourceUrl, locator: "chars:5-25", excerptSha256: "bc93bee13b017b8947c1f74da58b3770469be7cd32cc548b676c4394f9bc74b3" }

it("navigates to the exact captured evidence locator only after hash verification", async () => {
  render(<EvidencePanel evidence={[evidence]} activeCitation={citation} />)
  expect(await screen.findByTestId("evidence-excerpt")).toHaveTextContent("announced on July 11")
  expect(await screen.findByRole("link", { name: "Open original source" })).toHaveAttribute("href", evidence.sourceUrl)
})

it("does not invent a source link for operator evidence", () => {
  render(<EvidencePanel evidence={[{ ...evidence, sourceUrl: null }]} activeCitation={citation} />)
  expect(screen.queryByRole("link", { name: "Open original source" })).not.toBeInTheDocument()
  expect(screen.getByText("Operator-provided text")).toBeInTheDocument()
})

it("reports a missing immutable snapshot instead of resolving by key alone", () => {
  render(<EvidencePanel evidence={[evidence]} activeCitation={{ ...citation, evidenceSnapshotId: "missing" }} />)
  expect(screen.getByRole("alert")).toHaveTextContent("Evidence snapshot missing is unavailable")
  expect(screen.queryByTestId("evidence-excerpt")).not.toBeInTheDocument()
})

it("hides the excerpt and source link when the citation hash does not match", async () => {
  render(<EvidencePanel evidence={[evidence]} activeCitation={{ ...citation, excerptSha256: "0".repeat(64) }} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("Citation integrity verification failed")
  expect(screen.queryByTestId("evidence-excerpt")).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "Open original source" })).not.toBeInTheDocument()
})

it("uses automatic direction for evidence without a persisted evidence language", () => {
  render(<EvidencePanel evidence={[{ ...evidence, title: "منبع", contentText: "متن منبع" }]} activeCitation={null} />)

  expect(screen.getByText("منبع").closest("[data-testid='direction-boundary']")).toHaveAttribute("dir", "auto")
  expect(screen.getByText("متن منبع").closest("[data-testid='direction-boundary']")).not.toHaveAttribute("lang")
  expect(screen.getByText(/Snapshot hash/).closest("[data-testid='direction-boundary']")).toBeNull()
})
