"use client"

import { useEffect, useRef } from "react"

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",")

export function useEditorialModal({
  open,
  containerRef,
  initialFocusRef,
  onClose,
  canClose = true,
}: {
  open: boolean
  containerRef: React.RefObject<HTMLElement | null>
  initialFocusRef: React.RefObject<HTMLElement | null>
  onClose: () => void
  canClose?: boolean
}) {
  const openerRef = useRef<HTMLElement | null>(null)
  const closeRef = useRef(onClose)
  const canCloseRef = useRef(canClose)
  closeRef.current = onClose
  canCloseRef.current = canClose

  useEffect(() => {
    if (!open) return
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusInitial = () => (
      initialFocusRef.current
      ?? containerRef.current?.querySelector<HTMLElement>("[autofocus]")
      ?? focusable(containerRef.current)[0]
      ?? containerRef.current
    )?.focus()
    queueMicrotask(focusInitial)

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && canCloseRef.current) {
        event.preventDefault()
        closeRef.current()
        return
      }
      if (event.key !== "Tab") return
      const elements = focusable(containerRef.current)
      if (!elements.length) {
        event.preventDefault()
        containerRef.current?.focus()
        return
      }
      const first = elements[0]
      const last = elements[elements.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !containerRef.current?.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !containerRef.current?.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("keydown", onKeyDown)
      const opener = openerRef.current
      queueMicrotask(() => opener?.isConnected && opener.focus())
    }
  }, [containerRef, initialFocusRef, open])
}

function focusable(container: HTMLElement | null): HTMLElement[] {
  return container ? Array.from(container.querySelectorAll<HTMLElement>(focusableSelector)).filter((item) => !item.hasAttribute("disabled")) : []
}
