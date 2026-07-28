"use client"

import { LoaderCircle, Pencil, Trash2 } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { deleteArticleCollection, renameArticleCollection } from "./api"
import type { ArticleCollection } from "./types"

import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import { Button } from "@/components/ui/button"
import { ApiError, getApiErrorMessage } from "@/lib/http"

export function CollectionManagementControl({
  children,
  collection,
  onDeleted,
  onRenamed,
}: {
  children: (props: {
    "aria-controls": string | undefined
    "aria-expanded": boolean
    "aria-haspopup": "menu"
    buttonRef: React.Ref<HTMLButtonElement>
    onContextMenu: React.MouseEventHandler<HTMLButtonElement>
    onKeyDown: React.KeyboardEventHandler<HTMLButtonElement>
  }) => React.ReactNode
  collection: ArticleCollection
  onDeleted: (collection: ArticleCollection) => Promise<void>
  onRenamed: (collection: ArticleCollection) => Promise<void>
}) {
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number } | null>(null)
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const firstItemRef = useRef<HTMLButtonElement>(null)
  const secondItemRef = useRef<HTMLButtonElement>(null)
  const menuId = `collection-menu-${collection.id}`

  useEffect(() => {
    if (!menuPosition) return
    queueMicrotask(() => firstItemRef.current?.focus())
    const menu = menuRef.current
    if (menu) {
      const bounds = menu.getBoundingClientRect()
      const next = clampToViewport(menuPosition.left, menuPosition.top, bounds.width, bounds.height)
      if (next.left !== menuPosition.left || next.top !== menuPosition.top) setMenuPosition(next)
    }
    const closeOnOutsidePress = (event: PointerEvent) => {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return
      setMenuPosition(null)
    }
    const closeOnOutsideFocus = (event: FocusEvent) => {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return
      setMenuPosition(null)
    }
    document.addEventListener("pointerdown", closeOnOutsidePress)
    document.addEventListener("focusin", closeOnOutsideFocus)
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress)
      document.removeEventListener("focusin", closeOnOutsideFocus)
    }
  }, [menuPosition])

  function openAt(left: number, top: number) {
    setMenuPosition(clampToViewport(left, top, 160, 88))
  }

  function openFromPointer(event: React.MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    triggerRef.current = event.currentTarget
    openAt(event.clientX, event.clientY)
  }

  function handleTriggerKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return
    event.preventDefault()
    triggerRef.current = event.currentTarget
    const bounds = event.currentTarget.getBoundingClientRect()
    openAt(bounds.left + 24, bounds.bottom - 4)
  }

  function closeMenu(restoreFocus: boolean) {
    setMenuPosition(null)
    if (restoreFocus) queueMicrotask(() => triggerRef.current?.focus())
  }

  function handleMenuKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault()
      closeMenu(true)
      return
    }
    const items = [firstItemRef.current, secondItemRef.current].filter((item): item is HTMLButtonElement => Boolean(item))
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    let nextIndex: number | null = null
    if (event.key === "ArrowDown") nextIndex = index < 0 ? 0 : (index + 1) % items.length
    if (event.key === "ArrowUp") nextIndex = index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length
    if (event.key === "Home") nextIndex = 0
    if (event.key === "End") nextIndex = items.length - 1
    if (nextIndex === null) return
    event.preventDefault()
    items[nextIndex]?.focus()
  }

  function openDialog(nextDialog: "rename" | "delete") {
    triggerRef.current?.focus()
    setMenuPosition(null)
    setDialog(nextDialog)
  }

  return (
    <>
      {children({
        "aria-controls": menuPosition ? menuId : undefined,
        "aria-expanded": Boolean(menuPosition),
        "aria-haspopup": "menu",
        buttonRef: triggerRef,
        onContextMenu: openFromPointer,
        onKeyDown: handleTriggerKeyDown,
      })}

      {menuPosition ? (
        <div
          aria-label={`Manage ${collection.name}`}
          className="fixed z-40 w-40 rounded-lg border bg-background p-1 shadow-md"
          id={menuId}
          onKeyDown={handleMenuKeyDown}
          ref={menuRef}
          role="menu"
          style={menuPosition}
        >
          <button
            className="flex min-h-10 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-sm hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => openDialog("rename")}
            ref={firstItemRef}
            role="menuitem"
            type="button"
          >
            <Pencil className="size-3.5" aria-hidden="true" />
            Rename
          </button>
          <button
            className="flex min-h-10 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left text-sm text-destructive hover:bg-[var(--error-surface)] focus-visible:ring-2 focus-visible:ring-destructive/40"
            onClick={() => openDialog("delete")}
            ref={secondItemRef}
            role="menuitem"
            type="button"
          >
            <Trash2 className="size-3.5" aria-hidden="true" />
            Delete
          </button>
        </div>
      ) : null}

      <RenameCollectionDialog
        collection={collection}
        onClose={() => setDialog(null)}
        onRenamed={onRenamed}
        open={dialog === "rename"}
      />
      <DeleteCollectionDialog
        collection={collection}
        onClose={() => setDialog(null)}
        onDeleted={onDeleted}
        open={dialog === "delete"}
      />
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

function RenameCollectionDialog({
  collection,
  onClose,
  onRenamed,
  open,
}: {
  collection: ArticleCollection
  onClose: () => void
  onRenamed: (collection: ArticleCollection) => Promise<void>
  open: boolean
}) {
  const [name, setName] = useState(collection.name)
  const [touched, setTouched] = useState(false)
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const busyRef = useRef(false)
  const trimmedName = name.trim()
  const unchanged = normalizedName(trimmedName) === normalizedName(collection.name)
  const validationError = trimmedName.length === 0
    ? "Enter a collection name."
    : trimmedName.length > 60
      ? "Collection name must be 60 characters or fewer."
      : null

  useEffect(() => {
    if (!open) return
    setName(collection.name)
    setTouched(false)
    setServerError(null)
  }, [collection.name, open])

  function close() {
    if (pending || busyRef.current) return
    onClose()
  }

  useEditorialModal({ open, containerRef: dialogRef, initialFocusRef: inputRef, onClose: close, canClose: !pending })
  if (!open) return null

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (validationError || unchanged || pending || busyRef.current) return
    busyRef.current = true
    setPending(true)
    setServerError(null)
    try {
      const renamed = await renameArticleCollection(collection.id, trimmedName)
      await onRenamed(renamed)
      onClose()
    } catch (cause) {
      setServerError(getApiErrorMessage(cause, "Collection could not be renamed"))
    } finally {
      busyRef.current = false
      setPending(false)
    }
  }

  const showValidation = touched && validationError
  return (
    <div
      aria-describedby="rename-collection-description"
      aria-labelledby="rename-collection-title"
      aria-modal="true"
      className="nc-dialog-scrim fixed inset-0 z-50 grid place-items-center p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <form className="nc-dialog w-full max-w-md space-y-5 p-5" onSubmit={submit}>
        <div>
          <h2 className="text-lg font-semibold" id="rename-collection-title">Rename Collection</h2>
          <p className="mt-1 text-sm text-muted-foreground" id="rename-collection-description">
            Update this collection name without changing its saved articles.
          </p>
        </div>
        <label className="grid gap-1.5 text-sm font-medium" htmlFor={`rename-collection-${collection.id}`}>
          Collection name
          <input
            aria-label="Collection name"
            aria-describedby={showValidation ? "rename-collection-error" : undefined}
            aria-invalid={showValidation ? true : undefined}
            autoComplete="off"
            className="min-h-11 rounded-lg border bg-background px-3 text-base focus-visible:ring-2 focus-visible:ring-ring"
            disabled={pending}
            id={`rename-collection-${collection.id}`}
            maxLength={80}
            onBlur={() => setTouched(true)}
            onChange={(event) => {
              setName(event.target.value)
              setServerError(null)
            }}
            ref={inputRef}
            value={name}
          />
          <span className="flex justify-between gap-3 text-xs font-normal text-muted-foreground">
            <span>{unchanged && !validationError ? "Name is unchanged." : "1–60 characters"}</span>
            <span>{trimmedName.length}/60</span>
          </span>
        </label>
        {showValidation ? <p className="text-sm text-destructive" id="rename-collection-error" role="alert">{validationError}</p> : null}
        {serverError ? <p className="text-sm text-destructive" dir="auto" role="alert">{serverError}</p> : null}
        <div className="flex justify-end gap-2">
          <Button disabled={pending} onClick={close} type="button" variant="outline">Cancel</Button>
          <Button disabled={Boolean(validationError) || unchanged || pending} type="submit">
            {pending ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : null}
            {pending ? "Renaming…" : "Rename"}
          </Button>
        </div>
      </form>
    </div>
  )
}

function DeleteCollectionDialog({
  collection,
  onClose,
  onDeleted,
  open,
}: {
  collection: ArticleCollection
  onClose: () => void
  onDeleted: (collection: ArticleCollection) => Promise<void>
  open: boolean
}) {
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const busyRef = useRef(false)

  useEffect(() => {
    if (open) setServerError(null)
  }, [open])

  function close() {
    if (pending || busyRef.current) return
    onClose()
  }

  useEditorialModal({ open, containerRef: dialogRef, initialFocusRef: cancelRef, onClose: close, canClose: !pending })
  if (!open) return null

  async function remove() {
    if (pending || busyRef.current) return
    busyRef.current = true
    setPending(true)
    setServerError(null)
    try {
      await deleteArticleCollection(collection.id)
      await onDeleted(collection)
      onClose()
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        try {
          await onDeleted(collection)
          onClose()
        } catch (reconcileCause) {
          setServerError(getApiErrorMessage(reconcileCause, "Collection state could not be refreshed"))
        }
      } else {
        setServerError(getApiErrorMessage(cause, "Collection could not be deleted"))
      }
    } finally {
      busyRef.current = false
      setPending(false)
    }
  }

  return (
    <div
      aria-describedby="delete-collection-description"
      aria-labelledby="delete-collection-title"
      aria-modal="true"
      className="nc-dialog-scrim fixed inset-0 z-50 grid place-items-center p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <div className="nc-dialog w-full max-w-md space-y-5 p-5">
        <div>
          <h2 className="text-lg font-semibold" id="delete-collection-title">Delete Collection?</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground" id="delete-collection-description">
            <strong className="font-semibold text-foreground">{collection.name}</strong> contains {collection.articleCount} {collection.articleCount === 1 ? "saved article" : "saved articles"}.
            {" "}Deleting this collection removes only the folder and its memberships. Articles themselves are not deleted from NewsCraft.
          </p>
        </div>
        {serverError ? <p className="text-sm text-destructive" dir="auto" role="alert">{serverError}</p> : null}
        <div className="flex justify-end gap-2">
          <Button disabled={pending} onClick={close} ref={cancelRef} type="button" variant="outline">Cancel</Button>
          <Button disabled={pending} onClick={remove} type="button" variant="destructive">
            {pending ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <Trash2 className="size-4" aria-hidden="true" />}
            {pending ? "Deleting…" : "Delete Collection"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function normalizedName(value: string) {
  return value.trim().toLocaleLowerCase()
}
