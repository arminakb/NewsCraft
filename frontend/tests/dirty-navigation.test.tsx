import { fireEvent, render, screen } from "@testing-library/react"
import { DirtyNavigationCoordinator, guardedNavigation, useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"

function Harness({ handled, dirty = true }: { handled: () => void; dirty?: boolean }) {
  useDirtyNavigation(dirty)
  const click = (event: React.MouseEvent) => { event.preventDefault(); handled() }
  return <><DirtyNavigationCoordinator /><a href="/inbox" onClick={click}>Actionable</a><a href="/" onClick={click}>No-op</a><a href="#section" onClick={click}>Hash</a><a href="/file" download onClick={click}>Download</a><a href="/outside" target="_blank" onClick={click}>New tab</a></>
}

function Coordinated({ children }: { children: React.ReactNode }) {
  return <><DirtyNavigationCoordinator />{children}</>
}

function ReleasableDirtySource({ name }: { name: string }) {
  const release = useDirtyNavigation(true)
  return <button onClick={release}>{name}</button>
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

it("indexes clean app entry A before editor B becomes dirty", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "entry-a" }, "", "/inbox")
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
  const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
  const view = render(<Coordinated><Harness handled={vi.fn()} dirty={false} /></Coordinated>)
  const entryA = window.history.state
  window.history.pushState({ caller: "editor-b" }, "", "/review/revision-1")
  const editorB = window.history.state
  expect(confirm).not.toHaveBeenCalled()

  view.rerender(<Coordinated><Harness handled={vi.fn()} dirty /></Coordinated>)
  confirm.mockReturnValueOnce(false)
  window.dispatchEvent(new PopStateEvent("popstate", { state: entryA }))
  expect(go).toHaveBeenLastCalledWith(1)
  window.dispatchEvent(new PopStateEvent("popstate", { state: editorB }))
  confirm.mockReturnValueOnce(true)
  window.dispatchEvent(new PopStateEvent("popstate", { state: entryA }))
  expect(confirm).toHaveBeenCalledTimes(2)
  view.unmount()
  go.mockRestore()
  confirm.mockRestore()
})

it("releases only the persisted source before guarded navigation", () => {
  const action = vi.fn()
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  render(<Coordinated><ReleasableDirtySource name="Release legacy" /><ReleasableDirtySource name="Release exact" /></Coordinated>)
  fireEvent.click(screen.getByRole("button", { name: "Release legacy" }))
  expect(guardedNavigation(action)).toBe(false)
  expect(action).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Release exact" }))
  expect(guardedNavigation(action)).toBe(true)
  expect(action).toHaveBeenCalledOnce()
  expect(confirm).toHaveBeenCalledOnce()
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
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it("blocks backward and forward Navigation API transitions while edits are dirty", () => {
  const listeners = new Set<(event: NavigationEventLike) => void>()
  Object.defineProperty(window, "navigation", {
    configurable: true,
    value: {
      addEventListener: (_type: string, listener: (event: NavigationEventLike) => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: (event: NavigationEventLike) => void) => listeners.delete(listener),
    },
  })
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  const view = render(<Harness handled={vi.fn()} />)

  for (const path of ["/previous", "/forward"]) {
    const preventDefault = vi.fn()
    for (const listener of listeners) listener({ canIntercept: true, destination: { url: new URL(path, window.location.href).href }, preventDefault })
    expect(preventDefault).toHaveBeenCalledOnce()
  }

  view.unmount()
  expect(listeners).toHaveLength(0)
  confirm.mockRestore()
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
})

it("guards programmatic navigation once and does not leak an allow decision", async () => {
  const action = vi.fn()
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true).mockReturnValueOnce(false)
  render(<Harness handled={vi.fn()} />)

  expect(guardedNavigation(action)).toBe(false)
  expect(guardedNavigation(action)).toBe(true)
  expect(action).toHaveBeenCalledOnce()
  await Promise.resolve()
  expect(guardedNavigation(action)).toBe(false)
  expect(action).toHaveBeenCalledOnce()
  expect(confirm).toHaveBeenCalledTimes(3)
  confirm.mockRestore()
})

it("mounts the fallback without pushing an entry and preserves caller history state", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const push = vi.spyOn(window.history, "pushState")
  const view = render(<Harness handled={vi.fn()} />)

  expect(push).not.toHaveBeenCalled()
  expect(window.history.state).toMatchObject({ caller: "base" })
  view.unmount()
  push.mockRestore()
})

it("fallback restores canceled Back and Forward by their exact indexed delta", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
  const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
  render(<Harness handled={vi.fn()} />)
  const baseState = window.history.state
  window.history.pushState({ caller: "next" }, "", "/next")
  const nextState = window.history.state

  confirm.mockReturnValueOnce(false)
  window.dispatchEvent(new PopStateEvent("popstate", { state: baseState }))
  expect(go).toHaveBeenLastCalledWith(1)
  window.dispatchEvent(new PopStateEvent("popstate", { state: nextState }))

  confirm.mockReturnValueOnce(true)
  window.dispatchEvent(new PopStateEvent("popstate", { state: baseState }))
  confirm.mockReturnValueOnce(false)
  window.dispatchEvent(new PopStateEvent("popstate", { state: nextState }))
  expect(go).toHaveBeenLastCalledWith(-1)
  expect(confirm).toHaveBeenCalledTimes(4)
  go.mockRestore()
  confirm.mockRestore()
})

it("fallback suppression is consumed only by the exact restoration entry", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
  const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined)
  render(<Harness handled={vi.fn()} />)
  const baseState = window.history.state
  window.history.pushState({ caller: "next" }, "", "/next")
  const nextState = window.history.state as Record<string, unknown>
  confirm.mockReturnValueOnce(false)
  window.dispatchEvent(new PopStateEvent("popstate", { state: baseState }))

  window.dispatchEvent(new PopStateEvent("popstate", { state: { ...nextState, __newscraftNavigationIndex: 7 } }))
  expect(confirm).toHaveBeenCalledTimes(3)
  go.mockRestore()
  confirm.mockRestore()
})

it("fallback preserves push and replace caller state and becomes inert after unmount", () => {
  Object.defineProperty(window, "navigation", { configurable: true, value: undefined })
  window.history.replaceState({ caller: "base" }, "", "/base")
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
  const view = render(<Harness handled={vi.fn()} />)
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
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true)
  render(<Harness handled={vi.fn()} />)
  window.history.pushState("caller primitive", "", "/primitive")
  expect(window.history.state).toBe("caller primitive")
  confirm.mockRestore()
})

it("coordinates multiple dirty sources through one prompt", () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  const handled = vi.fn()
  render(<><Harness handled={handled} /><Harness handled={handled} /></>)
  fireEvent.click(screen.getAllByRole("link", { name: "Actionable" })[0])
  expect(confirm).toHaveBeenCalledOnce()
  expect(handled).not.toHaveBeenCalled()
  confirm.mockRestore()
})

type NavigationEventLike = { canIntercept: boolean; destination: { url: string }; preventDefault: () => void }
