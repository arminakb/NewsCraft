import { fireEvent, render, screen } from "@testing-library/react"

import { NodeContextMenu } from "@/features/automations/node-context-menu"

describe("workflow node context menu", () => {
  it("customizes the associated node with keyboard-accessible focus", () => {
    const onCustomize = vi.fn()
    const returnFocus = document.createElement("button")
    document.body.append(returnFocus)
    render(
      <NodeContextMenu
        menu={{ nodeId: "filter-2", nodeLabel: "Filter content", x: 24, y: 32, returnFocus, canDuplicate: true, canDelete: true }}
        onClose={vi.fn()}
        onCustomize={onCustomize}
        onDelete={vi.fn()}
        onDuplicate={vi.fn()}
      />,
    )

    const item = screen.getByRole("menuitem", { name: "Customize" })
    expect(item).toHaveFocus()
    fireEvent.keyDown(item, { key: "Enter" })
    fireEvent.click(item)
    expect(onCustomize).toHaveBeenCalledWith("filter-2", returnFocus)
    returnFocus.remove()
  })

  it("closes outside and on Escape, restoring node focus for Escape", () => {
    const onClose = vi.fn()
    const returnFocus = document.createElement("button")
    document.body.append(returnFocus)
    render(
      <NodeContextMenu
        menu={{ nodeId: "filter-1", nodeLabel: "Filter content", x: 24, y: 32, returnFocus, canDuplicate: true, canDelete: true }}
        onClose={onClose}
        onCustomize={vi.fn()}
        onDelete={vi.fn()}
        onDuplicate={vi.fn()}
      />,
    )

    fireEvent.pointerDown(document.body)
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(onClose).toHaveBeenCalledTimes(2)
    expect(returnFocus).toHaveFocus()
    returnFocus.remove()
  })

  it("supports arrow navigation and guards protected-node actions", () => {
    render(
      <NodeContextMenu
        menu={{ nodeId: "trigger-1", nodeLabel: "Manual", x: 24, y: 32, returnFocus: null, canDuplicate: false, canDelete: false }}
        onClose={vi.fn()}
        onCustomize={vi.fn()}
        onDelete={vi.fn()}
        onDuplicate={vi.fn()}
      />,
    )

    const customize = screen.getByRole("menuitem", { name: "Customize" })
    const duplicate = screen.getByRole("menuitem", { name: "Duplicate" })
    const deleteItem = screen.getByRole("menuitem", { name: "Delete" })
    expect(customize).toHaveFocus()
    fireEvent.keyDown(customize, { key: "End" })
    expect(customize).toHaveFocus()
    expect(duplicate).toBeDisabled()
    expect(deleteItem).toBeDisabled()
  })
})
