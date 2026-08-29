"use client"

import { createElement, useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"

import { DirtyNavigationDialog } from "@/components/editorial/dirty-navigation-dialog"

const historyIndexKey = "__newscraftNavigationIndex"
const dirtyEditors = new Map<symbol, string>()
const dirtyListeners = new Set<() => void>()
const coordinatorIds = new Set<symbol>()
const coordinatorListeners = new Set<() => void>()
let stopCoordinator: (() => void) | null = null
let dialogOwner: symbol | null = null
let allowedThisTurn = false
let unloadAllowedThisTurn = false
let unloadResetTimer: number | null = null
let allowedDestination: string | null = null
let replayingAnchor = false
let pendingNavigation: PendingNavigation | null = null
const pendingListeners = new Set<() => void>()

function activeMessage() {
  return dirtyEditors.values().next().value ?? "Discard unsaved revision edits?"
}

function pendingDescription(message: string) {
  if (message === "Discard unsaved workflow changes?") {
    return "You have unsaved changes in this workflow. Leaving now will discard them."
  }
  return "You have unsaved changes. Leaving now will discard them."
}

function withNavigationAllowed(action: () => void) {
  allowedThisTurn = true
  allowUnloadThisTurn()
  try { action() } finally { allowedThisTurn = false }
}

function allowUnloadThisTurn(duration = 0) {
  unloadAllowedThisTurn = true
  if (unloadResetTimer !== null) window.clearTimeout(unloadResetTimer)
  unloadResetTimer = window.setTimeout(() => {
    unloadAllowedThisTurn = false
    unloadResetTimer = null
  }, duration)
}

function allowDestinationOnce(url: string) {
  const key = navigationKey(url)
  allowedDestination = key
  allowUnloadThisTurn(5000)
  window.setTimeout(() => {
    if (allowedDestination === key) allowedDestination = null
  }, 5000)
}

function consumeAllowedDestination(url: string) {
  if (allowedDestination !== navigationKey(url)) return false
  return true
}

function requestPendingNavigation(action: () => void, message: string) {
  if (pendingNavigation) return false
  const activeElement = document.activeElement
  pendingNavigation = {
    action,
    message,
    returnFocus: activeElement instanceof HTMLElement ? activeElement : null,
  }
  queueMicrotask(notifyPendingListeners)
  return true
}

function cancelPendingNavigation() {
  if (!pendingNavigation) return
  pendingNavigation = null
  notifyPendingListeners()
}

function discardPendingNavigation() {
  const pending = pendingNavigation
  if (!pending) return
  pendingNavigation = null
  notifyPendingListeners()
  queueMicrotask(() => withNavigationAllowed(pending.action))
}

export function guardedNavigation(action: () => void, message = "Discard unsaved revision edits?") {
  if (dirtyEditors.size > 0 && !allowedThisTurn) {
    requestPendingNavigation(action, message)
    return false
  }
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
  const coordinatorId = useRef(Symbol("dirty-navigation-coordinator")).current
  const [isDialogOwner, setIsDialogOwner] = useState(false)
  const pending = useSyncExternalStore(
    subscribeToPendingNavigation,
    () => pendingNavigation,
    () => null,
  )

  useEffect(() => {
    const syncOwnership = () => setIsDialogOwner(dialogOwner === coordinatorId)
    coordinatorListeners.add(syncOwnership)
    const firstCoordinator = coordinatorIds.size === 0
    coordinatorIds.add(coordinatorId)
    if (dialogOwner === null) dialogOwner = coordinatorId
    notifyCoordinatorListeners()
    syncOwnership()
    if (firstCoordinator) stopCoordinator = startCoordinator()
    return () => {
      coordinatorIds.delete(coordinatorId)
      if (dialogOwner === coordinatorId) dialogOwner = coordinatorIds.values().next().value ?? null
      notifyCoordinatorListeners()
      coordinatorListeners.delete(syncOwnership)
      if (coordinatorIds.size === 0 && stopCoordinator) {
        const stop = stopCoordinator
        stopCoordinator = null
        stop()
        cancelPendingNavigation()
      }
    }
  }, [coordinatorId])
  if (!isDialogOwner) return null
  return createElement(DirtyNavigationDialog, {
    open: pending !== null,
    description: pendingDescription(pending?.message ?? "Discard unsaved revision edits?"),
    returnFocus: pending?.returnFocus ?? null,
    onCancel: cancelPendingNavigation,
    onDiscard: discardPendingNavigation,
  })
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
    if (consumeAllowedDestination(destination.href)) {
      if (replayingAnchor) return
      allowedDestination = null
    }
    if (dirtyEditors.size === 0 || allowedThisTurn) { allowDestinationOnce(destination.href); return }
    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation()
    requestPendingNavigation(() => {
      allowDestinationOnce(destination.href)
      const destinationKey = navigationKey(destination.href)
      replayingAnchor = true
      try { anchor.click() } finally { replayingAnchor = false }
      window.setTimeout(() => {
        if (navigationKey(window.location.href) !== destinationKey) window.location.assign(destination.href)
      }, 250)
    }, activeMessage())
  }
  const guardUnload = (event: BeforeUnloadEvent) => {
    if (dirtyEditors.size > 0 && !unloadAllowedThisTurn) event.preventDefault()
  }
  document.addEventListener("click", guardAnchor, true)
  window.addEventListener("beforeunload", guardUnload)

  const navigation = (window as Window & { navigation?: NavigationLike }).navigation
  const navigate = navigation?.navigate
  const guardNavigation = (event: NavigationEventLike) => {
    const allowedDestinationConsumed = consumeAllowedDestination(event.destination.url)
    if (!event.canIntercept || event.defaultPrevented || allowedThisTurn || allowedDestinationConsumed) return
    const destination = new URL(event.destination.url)
    const current = new URL(window.location.href)
    if (destination.origin !== current.origin || (destination.pathname === current.pathname && destination.search === current.search)) return
    if (dirtyEditors.size === 0) {
      allowUnloadThisTurn()
      return
    }
    event.preventDefault()
    requestPendingNavigation(() => {
      allowDestinationOnce(destination.href)
      if (typeof navigate === "function") navigate(destination.href)
      else window.location.assign(destination.href)
    }, activeMessage())
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
    replayingAnchor = false
  }
}

function startIndexedHistoryFallback() {
  const originalPush = history.pushState
  const originalReplace = history.replaceState
  const originalGo = history.go
  let currentIndex: number | null = readIndex(history.state) ?? 0
  let suppressedTarget: number | null = null
  let allowedPopTarget: number | null = null
  const annotatedCurrent = annotateState(history.state, currentIndex)
  originalReplace.call(history, annotatedCurrent, "", window.location.href)
  currentIndex = readIndex(annotatedCurrent)

  history.pushState = ((data: unknown, unused: string, url?: string | URL | null) => {
    const destination = new URL(url ?? window.location.href, window.location.href).href
    const performPush = () => {
      const nextIndex = currentIndex === null ? 0 : currentIndex + 1
      const annotated = annotateState(data, nextIndex)
      originalPush.call(history, annotated, unused, url)
      currentIndex = readIndex(annotated)
    }
    if (!allowedThisTurn && !consumeAllowedDestination(destination) && dirtyEditors.size > 0) {
      requestPendingNavigation(performPush, activeMessage())
      return
    }
    const nextIndex = currentIndex === null ? 0 : currentIndex + 1
    const annotated = annotateState(data, nextIndex)
    originalPush.call(history, annotated, unused, url)
    currentIndex = readIndex(annotated)
  }) as History["pushState"]
  history.replaceState = ((data: unknown, unused: string, url?: string | URL | null) => {
    const destination = new URL(url ?? window.location.href, window.location.href).href
    const performReplace = () => {
      const annotated = currentIndex === null ? data : annotateState(data, currentIndex)
      originalReplace.call(history, annotated, unused, url)
      currentIndex = readIndex(annotated)
    }
    if (!allowedThisTurn && !consumeAllowedDestination(destination) && dirtyEditors.size > 0) {
      requestPendingNavigation(performReplace, activeMessage())
      return
    }
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
    if (delta === 0 || allowedPopTarget === destinationIndex) {
      allowedPopTarget = null
      if (delta !== 0) allowUnloadThisTurn()
      return
    }
    if (dirtyEditors.size === 0 || allowedThisTurn) {
      if (delta !== 0) allowUnloadThisTurn()
      return
    }
    suppressedTarget = previousIndex
    originalGo.call(history, -delta)
    requestPendingNavigation(() => {
      allowedPopTarget = destinationIndex
      originalGo.call(history, delta)
    }, activeMessage())
  }
  window.addEventListener("popstate", onPopState)

  return () => {
    window.removeEventListener("popstate", onPopState)
    history.pushState = originalPush
    history.replaceState = originalReplace
    originalReplace.call(history, stripIndex(history.state), "", window.location.href)
    cancelPendingNavigation()
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

function subscribeToPendingNavigation(listener: () => void) {
  pendingListeners.add(listener)
  return () => pendingListeners.delete(listener)
}

function notifyPendingListeners() {
  pendingListeners.forEach((listener) => listener())
}

function notifyCoordinatorListeners() {
  coordinatorListeners.forEach((listener) => listener())
}

type NavigationLike = {
  addEventListener: (type: string, listener: (event: NavigationEventLike) => void) => void
  removeEventListener: (type: string, listener: (event: NavigationEventLike) => void) => void
  navigate?: (url: string) => void
}
type NavigationEventLike = { canIntercept: boolean; defaultPrevented?: boolean; destination: { url: string }; preventDefault: () => void }
type PendingNavigation = { action: () => void; message: string; returnFocus: HTMLElement | null }
