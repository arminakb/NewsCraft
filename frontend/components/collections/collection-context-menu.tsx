"use client"

import type { LucideIcon } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { flushSync } from "react-dom"

export type CollectionContextMenuAction = {
  destructive?: boolean
  icon: LucideIcon
  label: string
  onSelect: (trigger: HTMLButtonElement | null) => void
}

export function CollectionContextMenu({
  actions,
  children,
  label,
}: {
  actions: CollectionContextMenuAction[]
  children: (props: {
    "aria-controls": string | undefined
    "aria-expanded": boolean
    "aria-haspopup": "menu"
    buttonRef: React.Ref<HTMLButtonElement>
    onContextMenu: React.MouseEventHandler<HTMLButtonElement>
    onKeyDown: React.KeyboardEventHandler<HTMLButtonElement>
  }) => React.ReactNode
  label: string
}) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const firstItemRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!position) return
    queueMicrotask(() => firstItemRef.current?.focus())
    const menu = menuRef.current
    if (menu) {
      const bounds = menu.getBoundingClientRect()
      const next = clampToViewport(position.left, position.top, bounds.width, bounds.height)
      if (next.left !== position.left || next.top !== position.top) setPosition(next)
    }
    const closeOnOutsidePress = (event: PointerEvent) => {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return
      setPosition(null)
    }
    const closeOnOutsideFocus = (event: FocusEvent) => {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return
      setPosition(null)
    }
    document.addEventListener("pointerdown", closeOnOutsidePress)
    document.addEventListener("focusin", closeOnOutsideFocus)
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress)
      document.removeEventListener("focusin", closeOnOutsideFocus)
    }
  }, [position])

  function openAt(left: number, top: number) {
    setPosition(clampToViewport(left, top, 192, actions.length * 44 + 8))
  }

  function openFromPointer(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    triggerRef.current = event.currentTarget
    openAt(event.clientX, event.clientY)
  }

  function openFromKeyboard(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return
    event.preventDefault()
    triggerRef.current = event.currentTarget
    const bounds = event.currentTarget.getBoundingClientRect()
    openAt(bounds.left + 24, bounds.bottom - 4)
  }

  function close(restoreFocus: boolean) {
    setPosition(null)
    if (restoreFocus) queueMicrotask(() => triggerRef.current?.focus())
  }

  function handleMenuKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault()
      close(true)
      return
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return
    const items = [...menuRef.current!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : event.key === "ArrowDown"
          ? (current + 1) % items.length
          : (current - 1 + items.length) % items.length
    event.preventDefault()
    items[next]?.focus()
  }

  return (
    <>
      {children({
        "aria-controls": position ? menuId : undefined,
        "aria-expanded": Boolean(position),
        "aria-haspopup": "menu",
        buttonRef: triggerRef,
        onContextMenu: openFromPointer,
        onKeyDown: openFromKeyboard,
      })}
      {position ? (
        <div
          aria-label={label}
          className="fixed z-40 w-48 rounded-lg border border-border/70 bg-popover p-1 text-popover-foreground shadow-md"
          id={menuId}
          onKeyDown={handleMenuKeyDown}
          ref={menuRef}
          role="menu"
          style={position}
        >
          {actions.map((action, index) => {
            const Icon = action.icon
            return (
              <button
                className={action.destructive
                  ? "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-[13px] text-destructive outline-none hover:bg-[var(--error-surface)] focus-visible:bg-[var(--error-surface)] focus-visible:ring-2 focus-visible:ring-ring/50"
                  : "flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-[13px] outline-none hover:bg-navigation-hover focus-visible:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/50"}
                key={action.label}
                onClick={() => {
                  flushSync(() => setPosition(null))
                  triggerRef.current?.focus()
                  action.onSelect(triggerRef.current)
                }}
                ref={index === 0 ? firstItemRef : undefined}
                role="menuitem"
                type="button"
              >
                <Icon className="size-4" aria-hidden="true" />
                {action.label}
              </button>
            )
          })}
        </div>
      ) : null}
    </>
  )
}

function clampToViewport(left: number, top: number, width: number, height: number) {
  const gutter = 8
  return {
    left: Math.max(gutter, Math.min(left, window.innerWidth - width - gutter)),
    top: Math.max(gutter, Math.min(top, window.innerHeight - height - gutter)),
  }
}
