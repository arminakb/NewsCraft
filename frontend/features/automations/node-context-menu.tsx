"use client"

import { Copy, Settings2, Trash2 } from "lucide-react"
import { useEffect, useRef } from "react"

import { useDismissOnOutside, useMenuRovingFocus } from "@/components/ui/context-menu-behavior"

export type NodeContextMenuState = {
  nodeId: string
  nodeLabel: string
  x: number
  y: number
  returnFocus: HTMLElement | null
  canDuplicate: boolean
  duplicateDisabledReason?: string
  canDelete: boolean
  deleteDisabledReason?: string
}

export function NodeContextMenu({
  menu,
  onClose,
  onCustomize,
  onDuplicate,
  onDelete,
}: {
  menu: NodeContextMenuState
  onClose: () => void
  onCustomize: (nodeId: string, returnFocus: HTMLElement | null) => void
  onDuplicate: (nodeId: string) => void
  onDelete: (nodeId: string) => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)
  const itemRef = useRef<HTMLButtonElement>(null)
  const duplicateReasonId = `${menu.nodeId}-duplicate-disabled-reason`
  const deleteReasonId = `${menu.nodeId}-delete-disabled-reason`

  const moveMenuFocus = useMenuRovingFocus(menuRef, { skipDisabled: true })
  useDismissOnOutside(true, [menuRef], onClose)

  useEffect(() => {
    itemRef.current?.focus()
    const closeOnKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      event.preventDefault()
      onClose()
      menu.returnFocus?.focus()
    }
    document.addEventListener("keydown", closeOnKeyDown)
    return () => document.removeEventListener("keydown", closeOnKeyDown)
  }, [menu.returnFocus, onClose])

  return (
    <div
      aria-label={`${menu.nodeLabel} actions`}
      className="fixed z-20 w-48 rounded-lg border border-border/70 bg-popover p-1 text-popover-foreground shadow-md"
      onKeyDown={moveMenuFocus}
      ref={menuRef}
      role="menu"
      style={{ left: menu.x, top: menu.y }}
    >
      <button
        className="flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-[13px] outline-none hover:bg-navigation-hover focus-visible:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/50"
        onClick={() => onCustomize(menu.nodeId, menu.returnFocus)}
        ref={itemRef}
        role="menuitem"
        type="button"
      >
        <Settings2 className="size-4" aria-hidden="true" />
        Customize
      </button>
      {menu.duplicateDisabledReason ? <span className="sr-only" id={duplicateReasonId}>Duplicate unavailable: {menu.duplicateDisabledReason}</span> : null}
      <button
        className="flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-[13px] outline-none hover:bg-navigation-hover focus-visible:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        aria-describedby={menu.duplicateDisabledReason ? duplicateReasonId : undefined}
        disabled={!menu.canDuplicate}
        onClick={() => { onClose(); onDuplicate(menu.nodeId) }}
        role="menuitem"
        title={menu.duplicateDisabledReason ? `Duplicate unavailable: ${menu.duplicateDisabledReason}` : undefined}
        type="button"
      >
        <Copy className="size-4" aria-hidden="true" />
        Duplicate
      </button>
      {menu.deleteDisabledReason ? <span className="sr-only" id={deleteReasonId}>Delete unavailable: {menu.deleteDisabledReason}</span> : null}
      <button
        className="flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-[13px] text-destructive outline-none hover:bg-[var(--error-surface)] focus-visible:bg-[var(--error-surface)] focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
        aria-describedby={menu.deleteDisabledReason ? deleteReasonId : undefined}
        disabled={!menu.canDelete}
        onClick={() => { onClose(); onDelete(menu.nodeId) }}
        role="menuitem"
        title={menu.deleteDisabledReason ? `Delete unavailable: ${menu.deleteDisabledReason}` : undefined}
        type="button"
      >
        <Trash2 className="size-4" aria-hidden="true" />
        Delete
      </button>
    </div>
  )
}
