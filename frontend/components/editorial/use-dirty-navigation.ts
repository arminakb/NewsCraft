"use client"

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react"

const historyIndexKey = "__newscraftNavigationIndex"
const dirtyEditors = new Map<symbol, string>()
const dirtyListeners = new Set<() => void>()
let stopCoordinator: (() => void) | null = null
let coordinatorMounts = 0
let allowedThisTurn = false
let unloadAllowedThisTurn = false
let allowedDestination: string | null = null

function activeMessage() {
  return dirtyEditors.values().next().value ?? "Discard unsaved revision edits?"
}

function withNavigationAllowed(action: () => void) {
  allowedThisTurn = true
  allowUnloadThisTurn()
  try { action() } finally { allowedThisTurn = false }
}

function allowUnloadThisTurn() {
  unloadAllowedThisTurn = true
  window.setTimeout(() => { unloadAllowedThisTurn = false }, 0)
}

function allowDestinationOnce(url: string) {
  allowedDestination = navigationKey(url)
  allowUnloadThisTurn()
  queueMicrotask(() => { allowedDestination = null })
}

function consumeAllowedDestination(url: string) {
  if (allowedDestination !== navigationKey(url)) return false
  allowedDestination = null
  return true
}

function confirmNavigation() {
  return dirtyEditors.size === 0 || allowedThisTurn || window.confirm(activeMessage())
}

export function guardedNavigation(action: () => void, message = "Discard unsaved revision edits?") {
  if (dirtyEditors.size > 0 && !allowedThisTurn && !window.confirm(message)) return false
  withNavigationAllowed(action)
  return true
}

export function useDirtyNavigation(dirty: boolean, message = "Discard unsaved revision edits?") {
  const source = useRef(Symbol("dirty-editor"))
  const released = useRef(false)
  useEffect(() => {
    if (!dirty) {
      released.current = false
      if (dirtyEditors.delete(source.current)) notifyDirtyListeners()
      return
    }
    if (!released.current) {
      dirtyEditors.set(source.current, message)
      notifyDirtyListeners()
    }
    return () => {
      if (dirtyEditors.delete(source.current)) notifyDirtyListeners()
    }
  }, [dirty, message])
  return useCallback(() => {
    released.current = true
    if (dirtyEditors.delete(source.current)) notifyDirtyListeners()
  }, [])
}

export function useHasDirtyNavigation() {
  return useSyncExternalStore(
    subscribeToDirtyNavigation,
    () => dirtyEditors.size > 0,
    () => false,
  )
}

export function DirtyNavigationCoordinator() {
  useEffect(() => {
    coordinatorMounts += 1
    if (coordinatorMounts === 1) stopCoordinator = startCoordinator()
    return () => {
      coordinatorMounts -= 1
      if (coordinatorMounts === 0 && stopCoordinator) {
        const stop = stopCoordinator
        stopCoordinator = null
        stop()
      }
    }
  }, [])
  return null
}

function startCoordinator() {
  const guardAnchor = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = event.target
    const anchor = target instanceof Element ? target.closest<HTMLAnchorElement>("a[href]") : null
    if (!anchor || anchor.hasAttribute("download") || anchor.target.toLowerCase() === "_blank") return
    const rawHref = anchor.getAttribute("href")
    if (!rawHref || rawHref.startsWith("#")) return
    let destination: URL
    try { destination = new URL(anchor.href, window.location.href) } catch { return }
    if (destination.origin !== window.location.origin) return
    const current = new URL(window.location.href)
    if (destination.pathname === current.pathname && destination.search === current.search) return
    if (confirmNavigation()) { allowDestinationOnce(destination.href); return }
    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation()
  }
  const guardUnload = (event: BeforeUnloadEvent) => {
    if (dirtyEditors.size > 0 && !unloadAllowedThisTurn) event.preventDefault()
  }
  document.addEventListener("click", guardAnchor, true)
  window.addEventListener("beforeunload", guardUnload)

  const navigation = (window as Window & { navigation?: NavigationLike }).navigation
  const guardNavigation = (event: NavigationEventLike) => {
    if (!event.canIntercept || event.defaultPrevented || allowedThisTurn || consumeAllowedDestination(event.destination.url)) return
    const destination = new URL(event.destination.url)
    const current = new URL(window.location.href)
    if (destination.origin !== current.origin || (destination.pathname === current.pathname && destination.search === current.search)) return
    if (!confirmNavigation()) event.preventDefault()
    else allowUnloadThisTurn()
  }

  let stopHistory: () => void = () => undefined
  if (navigation) navigation.addEventListener("navigate", guardNavigation)
  else stopHistory = startIndexedHistoryFallback()

  return () => {
    document.removeEventListener("click", guardAnchor, true)
    window.removeEventListener("beforeunload", guardUnload)
    if (navigation) navigation.removeEventListener("navigate", guardNavigation)
    else stopHistory()
    allowedDestination = null
  }
}

function startIndexedHistoryFallback() {
  const originalPush = history.pushState
  const originalReplace = history.replaceState
  const originalGo = history.go
  let currentIndex: number | null = readIndex(history.state) ?? 0
  let suppressedTarget: number | null = null
  const annotatedCurrent = annotateState(history.state, currentIndex)
  originalReplace.call(history, annotatedCurrent, "", window.location.href)
  currentIndex = readIndex(annotatedCurrent)

  history.pushState = ((data: unknown, unused: string, url?: string | URL | null) => {
    const destination = new URL(url ?? window.location.href, window.location.href).href
    if (!allowedThisTurn && !consumeAllowedDestination(destination) && !confirmNavigation()) return
    const nextIndex = currentIndex === null ? 0 : currentIndex + 1
    const annotated = annotateState(data, nextIndex)
    originalPush.call(history, annotated, unused, url)
    currentIndex = readIndex(annotated)
  }) as History["pushState"]
  history.replaceState = ((data: unknown, unused: string, url?: string | URL | null) => {
    const destination = new URL(url ?? window.location.href, window.location.href).href
    if (!allowedThisTurn && !consumeAllowedDestination(destination) && !confirmNavigation()) return
    const annotated = currentIndex === null ? data : annotateState(data, currentIndex)
    originalReplace.call(history, annotated, unused, url)
    currentIndex = readIndex(annotated)
  }) as History["replaceState"]

  const onPopState = (event: PopStateEvent) => {
    const destinationIndex = readIndex(event.state)
    if (suppressedTarget !== null && destinationIndex === suppressedTarget) {
      suppressedTarget = null
      currentIndex = destinationIndex
      return
    }
    suppressedTarget = null
    if (destinationIndex === null || currentIndex === null) {
      currentIndex = destinationIndex
      return
    }
    const previousIndex = currentIndex
    const delta = destinationIndex - previousIndex
    currentIndex = destinationIndex
    if (delta === 0 || confirmNavigation()) {
      if (delta !== 0) allowUnloadThisTurn()
      return
    }
    suppressedTarget = previousIndex
    originalGo.call(history, -delta)
  }
  window.addEventListener("popstate", onPopState)

  return () => {
    window.removeEventListener("popstate", onPopState)
    history.pushState = originalPush
    history.replaceState = originalReplace
    originalReplace.call(history, stripIndex(history.state), "", window.location.href)
  }
}

function annotateState(state: unknown, index: number) {
  if (state === null || typeof state !== "object" || Array.isArray(state)) return state
  return { ...state, [historyIndexKey]: index }
}

function stripIndex(state: unknown) {
  if (state === null || typeof state !== "object" || Array.isArray(state)) return state
  const { [historyIndexKey]: _index, ...callerState } = state as Record<string, unknown>
  return callerState
}

function readIndex(state: unknown) {
  if (state === null || typeof state !== "object" || Array.isArray(state)) return null
  const value = (state as Record<string, unknown>)[historyIndexKey]
  return typeof value === "number" && Number.isSafeInteger(value) ? value : null
}

function navigationKey(url: string) {
  const destination = new URL(url, window.location.href)
  return `${destination.origin}${destination.pathname}${destination.search}`
}

function subscribeToDirtyNavigation(listener: () => void) {
  dirtyListeners.add(listener)
  return () => dirtyListeners.delete(listener)
}

function notifyDirtyListeners() {
  dirtyListeners.forEach((listener) => listener())
}

type NavigationLike = {
  addEventListener: (type: string, listener: (event: NavigationEventLike) => void) => void
  removeEventListener: (type: string, listener: (event: NavigationEventLike) => void) => void
}
type NavigationEventLike = { canIntercept: boolean; defaultPrevented?: boolean; destination: { url: string }; preventDefault: () => void }
