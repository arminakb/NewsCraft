import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useRef } from "react"

import { EditorialDialog } from "@/components/editorial/editorial-dialog"

function Harness({ canClose = true, onClose, open = true }: { canClose?: boolean; onClose: () => void; open?: boolean }) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  return (
    <EditorialDialog
      canClose={canClose}
      describedBy="harness-description"
      initialFocusRef={cancelRef}
      labelledBy="harness-title"
      onClose={onClose}
      open={open}
    >
      <div className="nc-dialog">
        <h2 id="harness-title">Harness Dialog</h2>
        <p id="harness-description">Body copy.</p>
        <button ref={cancelRef} type="button">Cancel</button>
        <button type="button">Confirm</button>
      </div>
    </EditorialDialog>
  )
}

describe("EditorialDialog", () => {
  it("renders nothing while closed", () => {
    render(<Harness onClose={vi.fn()} open={false} />)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("exposes the modal scaffold and moves focus to the initial target", async () => {
    render(<Harness onClose={vi.fn()} />)

    const dialog = screen.getByRole("dialog", { name: "Harness Dialog" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveClass("nc-dialog-scrim")
    expect(dialog).toHaveAccessibleDescription("Body copy.")
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus())
  })

  it("closes on scrim dismissal and on Escape", async () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)

    fireEvent.mouseDown(screen.getByRole("dialog"))
    expect(onClose).toHaveBeenCalledTimes(1)

    fireEvent.keyDown(document, { key: "Escape" })
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it("keeps the dialog open while busy", () => {
    const onClose = vi.fn()
    render(<Harness canClose={false} onClose={onClose} />)

    fireEvent.mouseDown(screen.getByRole("dialog"))
    fireEvent.keyDown(document, { key: "Escape" })
    expect(onClose).not.toHaveBeenCalled()
  })

  it("does not close when the dismissal starts inside the dialog body", () => {
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)

    fireEvent.mouseDown(screen.getByRole("button", { name: "Confirm" }))
    expect(onClose).not.toHaveBeenCalled()
  })

  it("restores focus to the opener when it unmounts", async () => {
    function Opener() {
      const cancelRef = useRef<HTMLButtonElement>(null)
      return (
        <>
          <button type="button">Open</button>
          <EditorialDialog initialFocusRef={cancelRef} labelledBy="harness-title" onClose={vi.fn()} open>
            <div>
              <h2 id="harness-title">Harness Dialog</h2>
              <button ref={cancelRef} type="button">Cancel</button>
            </div>
          </EditorialDialog>
        </>
      )
    }

    const opener = document.createElement("button")
    opener.textContent = "Trigger"
    document.body.append(opener)
    opener.focus()

    const view = render(<Opener />)
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus())

    view.unmount()
    await waitFor(() => expect(opener).toHaveFocus())
    opener.remove()
  })
})
