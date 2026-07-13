import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { useState } from "react"
import { createManualStory } from "@/lib/editorial-api"
import { ManualIntakeDialog } from "@/components/editorial/manual-intake-dialog"

vi.mock("@/lib/editorial-api", () => ({ createManualStory: vi.fn() }))

it("validates operator text and closes only after the durable job is accepted", async () => {
  vi.mocked(createManualStory).mockImplementation(() => new Promise(() => undefined))
  const onClose = vi.fn()
  render(<ManualIntakeDialog open onClose={onClose} />)
  fireEvent.click(screen.getByRole("tab", { name: "Text" }))
  expect(screen.getByLabelText("Story title")).toHaveAttribute("data-testid", "direction-boundary")
  expect(screen.getByLabelText("Story title")).toHaveAttribute("dir", "auto")
  expect(screen.getByLabelText("Source label")).toHaveAttribute("dir", "auto")
  expect(screen.getByLabelText("Story text")).toHaveAttribute("dir", "auto")
  fireEvent.change(screen.getByLabelText("Story title"), { target: { value: "Operator lead" } })
  fireEvent.change(screen.getByLabelText("Source label"), { target: { value: "News desk" } })
  fireEvent.change(screen.getByLabelText("Story text"), { target: { value: "too short" } })
  expect(screen.getByRole("button", { name: "Add story" })).toBeDisabled()
  fireEvent.change(screen.getByLabelText("Story text"), { target: { value: "This operator text is long enough to preserve." } })
  fireEvent.click(screen.getByRole("button", { name: "Add story" }))
  expect(onClose).not.toHaveBeenCalled()

  vi.mocked(createManualStory).mockResolvedValue({ jobId: "job-1", status: "queued", deduplicated: false })
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
  render(<ManualIntakeDialog open onClose={onClose} />)
  fireEvent.change(screen.getAllByLabelText("Story URL").at(-1)!, { target: { value: "https://example.com/report" } })
  fireEvent.click(screen.getAllByRole("button", { name: "Add story" }).at(-1)!)
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(onClose).toHaveBeenLastCalledWith(expect.objectContaining({ jobId: "job-1" }))
})

it("traps focus, closes on Escape, and restores the opener", async () => {
  function Harness() {
    const [open, setOpen] = useState(false)
    return <><button onClick={() => setOpen(true)}>Open manual intake</button><ManualIntakeDialog open={open} onClose={() => setOpen(false)} /></>
  }
  render(<Harness />)
  const opener = screen.getByRole("button", { name: "Open manual intake" })
  opener.focus()
  fireEvent.click(opener)
  const dialog = screen.getByRole("dialog", { name: "Add story manually" })
  const url = within(dialog).getByLabelText("Story URL")
  await waitFor(() => expect(url).toHaveFocus())
  url.focus()
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true })
  expect(dialog).toContainElement(document.activeElement as HTMLElement)
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByRole("dialog", { name: "Add story manually" })).not.toBeInTheDocument()
  await waitFor(() => expect(opener).toHaveFocus())
})
