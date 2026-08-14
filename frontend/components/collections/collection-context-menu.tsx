"use client"

import type { LucideIcon } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { flushSync } from "react-dom"

import { useDismissOnOutside, useMenuRovingFocus } from "@/components/ui/context-menu-behavior"

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

  const moveMenuFocus = useMenuRovingFocus(menuRef)
  useDismissOnOutside(
    Boolean(position),
    [menuRef, triggerRef],
    () => setPosition(null),
    { includeFocus: true },
  )

  useEffect(() => {
    if (!position) return
    queueMicrotask(() => firstItemRef.current?.focus())
    const menu = menuRef.current
    if (!menu) return
    const bounds = menu.getBoundingClientRect()
    const next = clampToViewport(position.left, position.top, bounds.width, bounds.height)
    if (next.left !== position.left || next.top !== position.top) setPosition(next)
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
    moveMenuFocus(event)
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
