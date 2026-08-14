"use client"

import { useCallback, useEffect, useRef } from "react"

const ROVING_KEYS = ["ArrowDown", "ArrowUp", "Home", "End"]

/**
 * Roving focus for coordinate-positioned context menus: ArrowDown/ArrowUp wrap
 * around the `[role="menuitem"]` children, Home/End jump to the edges. Returns a
 * handler that reports whether it consumed the key so callers can keep their own
 * Escape handling in front of it.
 */
export function useMenuRovingFocus(
  menuRef: React.RefObject<HTMLElement | null>,
  { skipDisabled = false }: { skipDisabled?: boolean } = {},
) {
  return useCallback((event: React.KeyboardEvent): boolean => {
    if (!ROVING_KEYS.includes(event.key)) return false
    const menu = menuRef.current
    if (!menu) return false
    const items = [...menu.querySelectorAll<HTMLElement>(
      skipDisabled ? '[role="menuitem"]:not(:disabled)' : '[role="menuitem"]',
    )]
    if (!items.length) return false
    const current = items.indexOf(document.activeElement as HTMLElement)
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : event.key === "ArrowDown"
          ? (current + 1) % items.length
          : (current - 1 + items.length) % items.length
    event.preventDefault()
    items[next]?.focus()
    return true
  }, [menuRef, skipDisabled])
}

/**
 * Dismisses an open overlay when a pointer press (and optionally a focus move)
 * lands outside every element in `refs`. Listeners are only registered while
 * `enabled` is true so closed menus cost nothing.
 */
export function useDismissOnOutside(
  enabled: boolean,
  refs: ReadonlyArray<React.RefObject<HTMLElement | null>>,
  onDismiss: () => void,
  { includeFocus = false }: { includeFocus?: boolean } = {},
) {
  const latest = useRef({ onDismiss, refs })
  useEffect(() => {
    latest.current = { onDismiss, refs }
  })

  useEffect(() => {
    if (!enabled) return
    const dismissIfOutside = (event: Event) => {
      const target = event.target as globalThis.Node | null
      const { onDismiss: dismiss, refs: current } = latest.current
      if (current.some((ref) => target && ref.current?.contains(target))) return
      dismiss()
    }
    document.addEventListener("pointerdown", dismissIfOutside)
    if (includeFocus) document.addEventListener("focusin", dismissIfOutside)
    return () => {
      document.removeEventListener("pointerdown", dismissIfOutside)
      if (includeFocus) document.removeEventListener("focusin", dismissIfOutside)
    }
  }, [enabled, includeFocus])
}
