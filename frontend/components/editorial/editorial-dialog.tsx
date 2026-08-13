"use client"

import { useRef } from "react"

import { useEditorialModal } from "./use-editorial-modal"

import { cn } from "@/lib/utils"

const SCRIM_CLASSES = "nc-dialog-scrim fixed inset-0 z-50 grid place-items-center p-4"

/**
 * The editorial modal scaffold: a full-viewport scrim that is itself the
 * `role="dialog"` container, with focus trapping, Escape handling and opener
 * refocus supplied by `useEditorialModal`, plus a busy gate (`canClose`) that
 * suppresses both scrim dismissal and Escape while a mutation is in flight.
 *
 * Callers render only the dialog body (typically an `.nc-dialog` element).
 */
export function EditorialDialog({
  canClose = true,
  children,
  className,
  describedBy,
  initialFocusRef,
  labelledBy,
  onClose,
  open,
}: {
  canClose?: boolean
  children: React.ReactNode
  className?: string
  describedBy?: string
  initialFocusRef: React.RefObject<HTMLElement | null>
  labelledBy: string
  onClose: () => void
  open: boolean
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEditorialModal({ open, containerRef, initialFocusRef, onClose, canClose })

  if (!open) return null

  return (
    <div
      aria-describedby={describedBy}
      aria-labelledby={labelledBy}
      aria-modal="true"
      className={cn(SCRIM_CLASSES, className)}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && canClose) onClose()
      }}
      ref={containerRef}
      role="dialog"
      tabIndex={-1}
    >
      {children}
    </div>
  )
}
