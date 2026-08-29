import { act, fireEvent, render, screen } from "@testing-library/react"
import { DirtyNavigationCoordinator, guardedNavigation, useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"

const workflowDescription = "You have unsaved changes in this workflow. Leaving now will discard them."

function Harness({ handled, dirty = true }: { handled: () => void; dirty?: boolean }) {
  useDirtyNavigation(dirty, "Discard unsaved workflow changes?")
  const click = (event: React.MouseEvent) => { event.preventDefault(); handled() }
  return <><DirtyNavigationCoordinator /><a href="/sources" onClick={click}>Actionable</a><a href="/" onClick={click}>No-op</a><a href="#section" onClick={click}>Hash</a><a href="/file" download onClick={click}>Download</a><a href="/outside" target="_blank" onClick={click}>New tab</a></>
}

function Coordinated({ children }: { children: React.ReactNode }) {
  return <><DirtyNavigationCoordinator />{children}</>
}

function ReleasableDirtySource({ name }: { name: string }) {
  const release = useDirtyNavigation(true)
  return <button onClick={release}>{name}</button>
}

async function expectUnsavedDialog(description = workflowDescription) {
  const dialog = await screen.findByRole("dialog", { name: "Unsaved changes" })
  expect(dialog).toHaveTextContent(description)
  expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Discard changes" })).toBeInTheDocument()
  return dialog
}

async function clickDialogButton(name: "Cancel" | "Discard changes") {
  fireEvent.click(screen.getByRole("button", { name }))
  await act(async () => { await Promise.resolve() })
}

it("does not alter beforeunload when the root coordinator has no dirty sources", () => {
  render(<DirtyNavigationCoordinator />)
  const unload = new Event("beforeunload", { cancelable: true })
  const returnValueSet = vi.fn()
  Object.defineProperty(unload, "returnValue", { configurable: true, get: () => undefined, set: returnValueSet })
  window.dispatchEvent(unload)
  expect(unload.defaultPrevented).toBe(false)
  expect(returnValueSet).not.toHaveBeenCalled()
})

it("blocks unload only until the last dirty source is synchronously released", () => {
  render(<Coordinated><ReleasableDirtySource name="Release source" /></Coordinated>)
  const dirtyUnload = new Event("beforeunload", { cancelable: true })
  window.dispatchEvent(dirtyUnload)
  expect(dirtyUnload.defaultPrevented).toBe(true)

  fireEvent.click(screen.getByRole("button", { name: "Release source" }))
  const cleanUnload = new Event("beforeunload", { cancelable: true })
  window.dispatchEvent(cleanUnload)
  expect(cleanUnload.defaultPrevented).toBe(false)
})

it("indexes clean app entry A before editor B becomes dirty", async () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "entry-a" }, "", "/sources")
  const confirm = vi.spyOn(window, "confirm")
  const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
  const view = render(<Coordinated><Harness handled={vi.fn()} dirty={false} /></Coordinated>)
  const entryA = window.history.state
  window.history.pushState({ caller: "editor-b" }, "", "/review/revision-1")
  const editorB = window.history.state

  view.rerender(<Coordinated><Harness handled={vi.fn()} dirty /></Coordinated>)
  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: entryA })) })
  expect(go).toHaveBeenLastCalledWith(1)
  await expectUnsavedDialog()
  await clickDialogButton("Cancel")

  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: editorB })) })
  expect(screen.queryByRole("dialog", { name: "Unsaved changes" })).not.toBeInTheDocument()
  expect(confirm).not.toHaveBeenCalled()
  view.unmount()
  go.mockRestore()
  confirm.mockRestore()
})

it("uses the custom dialog for guarded navigation and does not call native confirm", async () => {
  const action = vi.fn()
  const confirm = vi.spyOn(window, "confirm")
  render(<Coordinated><ReleasableDirtySource name="Release legacy" /><ReleasableDirtySource name="Release exact" /></Coordinated>)
  fireEvent.click(screen.getByRole("button", { name: "Release legacy" }))
  let guardedResult = true
  act(() => { guardedResult = guardedNavigation(action) })
  expect(guardedResult).toBe(false)
  expect(action).not.toHaveBeenCalled()
  await expectUnsavedDialog("You have unsaved changes. Leaving now will discard them.")
  await clickDialogButton("Cancel")

  fireEvent.click(screen.getByRole("button", { name: "Release exact" }))
  act(() => { guardedResult = guardedNavigation(action) })
  expect(guardedResult).toBe(true)
  expect(action).toHaveBeenCalledOnce()
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it("preserves the selected internal link destination through Cancel and Discard", async () => {
  const handled = vi.fn()
  const confirm = vi.spyOn(window, "confirm")
  render(<Harness handled={handled} />)

  fireEvent.click(screen.getByRole("link", { name: "Actionable" }))
  await expectUnsavedDialog()
  expect(confirm).not.toHaveBeenCalled()
  await clickDialogButton("Cancel")
  expect(screen.queryByRole("dialog", { name: "Unsaved changes" })).not.toBeInTheDocument()
  expect(handled).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole("link", { name: "Actionable" }))
  await expectUnsavedDialog()
  await clickDialogButton("Discard changes")
  expect(handled).toHaveBeenCalledOnce()
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it("allows clean internal navigation without a warning", () => {
  const handled = vi.fn()
  const confirm = vi.spyOn(window, "confirm")
  render(<Harness handled={handled} dirty={false} />)
  fireEvent.click(screen.getByRole("link", { name: "Actionable" }))
  expect(handled).toHaveBeenCalledOnce()
  expect(screen.queryByRole("dialog", { name: "Unsaved changes" })).not.toBeInTheDocument()
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it("ignores modified clicks, downloads, new tabs, hashes, and same-location links", () => {
  window.history.replaceState({}, "", "/")
  const handled = vi.fn()
  const confirm = vi.spyOn(window, "confirm")
  render(<Harness handled={handled} />)
  fireEvent.click(screen.getByRole("link", { name: "Actionable" }), { ctrlKey: true })
  fireEvent.click(screen.getByRole("link", { name: "No-op" }))
  fireEvent.click(screen.getByRole("link", { name: "Hash" }))
  fireEvent.click(screen.getByRole("link", { name: "Download" }))
  fireEvent.click(screen.getByRole("link", { name: "New tab" }))
  expect(handled).toHaveBeenCalledTimes(5)
  expect(screen.queryByRole("dialog", { name: "Unsaved changes" })).not.toBeInTheDocument()
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it("blocks backward and forward Navigation API transitions with one custom dialog", async () => {
  const listeners = new Set<(event: NavigationEventLike) => void>()
  Object.defineProperty(window, "navigation", {
    configurable: true,
    value: {
      addEventListener: (_type: string, listener: (event: NavigationEventLike) => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: (event: NavigationEventLike) => void) => listeners.delete(listener),
    },
  })
  const confirm = vi.spyOn(window, "confirm")
  const view = render(<Harness handled={vi.fn()} />)

  for (const path of ["/previous", "/forward"]) {
    const preventDefault = vi.fn()
    act(() => {
      for (const listener of listeners) listener({ canIntercept: true, destination: { url: new URL(path, window.location.href).href }, preventDefault })
    })
    expect(preventDefault).toHaveBeenCalledOnce()
    await expectUnsavedDialog()
    await clickDialogButton("Cancel")
  }

  view.unmount()
  expect(listeners).toHaveLength(0)
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
})

it("guards programmatic navigation until the user chooses an action", async () => {
  const action = vi.fn()
  const confirm = vi.spyOn(window, "confirm")
  render(<Harness handled={vi.fn()} />)

  let guardedResult = true
  act(() => { guardedResult = guardedNavigation(action, "Discard unsaved workflow changes?") })
  expect(guardedResult).toBe(false)
  await expectUnsavedDialog()
  await clickDialogButton("Cancel")
  act(() => { guardedResult = guardedNavigation(action, "Discard unsaved workflow changes?") })
  expect(guardedResult).toBe(false)
  await expectUnsavedDialog()
  await clickDialogButton("Discard changes")
  expect(action).toHaveBeenCalledOnce()
  expect(confirm).not.toHaveBeenCalled()

  act(() => { guardedResult = guardedNavigation(action, "Discard unsaved workflow changes?") })
  expect(guardedResult).toBe(false)
  await expectUnsavedDialog()
  expect(action).toHaveBeenCalledOnce()
  confirm.mockRestore()
})

it("mounts the fallback without pushing an entry and preserves caller history state", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm")
  const push = vi.spyOn(window.history, "pushState")
  const view = render(<Harness handled={vi.fn()} dirty={false} />)

  expect(push).not.toHaveBeenCalled()
  expect(window.history.state).toMatchObject({ caller: "base" })
  view.unmount()
  expect(confirm).not.toHaveBeenCalled()
  push.mockRestore()
  confirm.mockRestore()
})

it("fallback restores canceled Back and Forward by their exact indexed delta", async () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm")
  const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
  const view = render(<Harness handled={vi.fn()} dirty={false} />)
  const baseState = window.history.state
  window.history.pushState({ caller: "next" }, "", "/next")
  const nextState = window.history.state
  view.rerender(<Harness handled={vi.fn()} />)

  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: baseState })) })
  expect(go).toHaveBeenLastCalledWith(1)
  await expectUnsavedDialog()
  await clickDialogButton("Cancel")
  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: nextState })) })
  expect(screen.queryByRole("dialog", { name: "Unsaved changes" })).not.toBeInTheDocument()

  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: baseState })) })
  await expectUnsavedDialog()
  await clickDialogButton("Discard changes")
  expect(go).toHaveBeenLastCalledWith(-1)
  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: baseState })) })

  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: nextState })) })
  await expectUnsavedDialog()
  await clickDialogButton("Cancel")
  expect(go).toHaveBeenLastCalledWith(-1)
  expect(confirm).not.toHaveBeenCalled()
  view.unmount()
  go.mockRestore()
  confirm.mockRestore()
})

it("fallback suppression is consumed only by the exact restoration entry", async () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm")
  const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
  const view = render(<Harness handled={vi.fn()} dirty={false} />)
  const baseState = window.history.state
  window.history.pushState({ caller: "next" }, "", "/next")
  const nextState = window.history.state as Record<string, unknown>
  view.rerender(<Harness handled={vi.fn()} />)

  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: baseState })) })
  await expectUnsavedDialog()
  await clickDialogButton("Cancel")
  act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: { ...nextState, __newscraftNavigationIndex: 7 } })) })
  await expectUnsavedDialog()
  await clickDialogButton("Cancel")
  expect(confirm).not.toHaveBeenCalled()
  view.unmount()
  go.mockRestore()
  confirm.mockRestore()
})

it("fallback preserves push and replace caller state and becomes inert after unmount", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm")
  const view = render(<Harness handled={vi.fn()} dirty={false} />)
  window.history.pushState({ caller: "pushed", nested: { exact: true } }, "", "/pushed")
  expect(window.history.state).toMatchObject({ caller: "pushed", nested: { exact: true } })
  window.history.replaceState({ caller: "replaced" }, "", "/replaced")
  expect(window.history.state).toMatchObject({ caller: "replaced" })
  const callsBeforeUnmount = confirm.mock.calls.length

  view.unmount()
  window.history.pushState({ caller: "clean" }, "", "/clean")
  expect(window.history.state).toEqual({ caller: "clean" })
  expect(confirm).toHaveBeenCalledTimes(callsBeforeUnmount)
  confirm.mockRestore()
})

it("fallback leaves primitive caller history state unchanged and treats it as unindexed", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm")
  render(<Harness handled={vi.fn()} dirty={false} />)
  window.history.pushState("caller primitive", "", "/primitive")
  expect(window.history.state).toBe("caller primitive")
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it("coordinates multiple dirty sources through one custom dialog", async () => {
  const confirm = vi.spyOn(window, "confirm")
  const handled = vi.fn()
  render(<><Harness handled={handled} /><Harness handled={handled} /></>)
  fireEvent.click(screen.getAllByRole("link", { name: "Actionable" })[0])
  await expectUnsavedDialog()
  expect(screen.getAllByRole("dialog", { name: "Unsaved changes" })).toHaveLength(1)
  expect(handled).not.toHaveBeenCalled()
  expect(confirm).not.toHaveBeenCalled()
  await clickDialogButton("Cancel")
  confirm.mockRestore()
})

type NavigationEventLike = { canIntercept: boolean; destination: { url: string }; preventDefault: () => void }
