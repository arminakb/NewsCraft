"use client"

import { Folder, FolderOpen, FolderPlus, Inbox } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { createArticleCollection } from "./api"
import { CollectionManagementControl } from "./collection-management"
import type { ArticleCollection } from "./types"

import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import { Button } from "@/components/ui/button"
import { formatNumber } from "@/lib/format"
import { getApiErrorMessage } from "@/lib/http"
import { cn } from "@/lib/utils"

type CollectionsSidebarProps = {
  collections: ArticleCollection[] | undefined
  error: unknown
  pending: boolean
  selectedId: string | null
  onCreated: (collection: ArticleCollection) => void
  onDeleted: (collection: ArticleCollection) => Promise<void>
  onRenamed: (collection: ArticleCollection) => Promise<void>
  onRetry: () => void
  onSelect: (collectionId: string | null) => void
  focusAllFeedToken: number
}

export function CollectionsSidebar({
  collections,
  error,
  pending,
  selectedId,
  onCreated,
  onDeleted,
  onRenamed,
  onRetry,
  onSelect,
  focusAllFeedToken,
}: CollectionsSidebarProps) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const allFeedRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!focusAllFeedToken) return
    queueMicrotask(() => allFeedRef.current?.focus())
  }, [focusAllFeedToken])

  return (
    <aside
      aria-label="Collections"
      className="sticky top-14 hidden h-[calc(100vh-3.5rem)] min-w-0 overflow-y-auto border-r bg-slate-50/55 min-[900px]:block"
    >
      <div className="space-y-5 p-3 lg:p-4">
        <nav aria-label="Library collections">
          <CollectionButton
            active={selectedId === null}
            count={null}
            icon={Inbox}
            label="All articles"
            onClick={() => onSelect(null)}
            buttonRef={allFeedRef}
          />

          <div className="mt-5 flex items-center justify-between gap-2 px-2">
            <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Collections
            </h2>
            <span className="group/new-collection relative inline-flex">
              <Button
                aria-label="Create new collection"
                className="size-8 min-h-8 min-w-8"
                disabled={pending || Boolean(error)}
                onClick={() => setDialogOpen(true)}
                size="icon"
                title="New collection"
                variant="ghost"
              >
                <FolderPlus className="size-4" aria-hidden="true" />
              </Button>
              <span
                className="pointer-events-none absolute right-0 top-full z-20 mt-1 hidden w-max rounded-md bg-foreground px-2 py-1 text-xs normal-case tracking-normal text-background shadow-md group-hover/new-collection:block group-focus-within/new-collection:block"
                role="tooltip"
              >
                New collection
              </span>
            </span>
          </div>

          <div className="mt-2">
            {pending ? (
              <div aria-label="Loading collections" className="space-y-2 px-2 py-1" role="status">
                <span className="sr-only">Loading collections</span>
                {["w-4/5", "w-3/5", "w-5/6"].map((width) => (
                  <div aria-hidden="true" className="flex h-10 animate-pulse items-center gap-2" key={width}>
                    <span className="size-4 rounded bg-muted" />
                    <span className={cn("h-3 rounded bg-muted", width)} />
                  </div>
                ))}
              </div>
            ) : null}

            {error ? (
              <div className="space-y-2 rounded-lg border bg-background p-3">
                <p className="text-xs text-red-700" dir="auto" role="alert">
                  {getApiErrorMessage(error, "Collections could not be loaded")}
                </p>
                <Button className="min-h-9 w-full" onClick={onRetry} size="sm" variant="outline">
                  Retry
                </Button>
              </div>
            ) : null}

            {!pending && !error && collections?.length === 0 ? (
              <p className="px-2 py-3 text-xs leading-5 text-muted-foreground">No collections yet.</p>
            ) : null}

            {!pending && !error && collections?.length ? (
              <ul className="space-y-1">
                {collections.map((collection) => (
                  <li className="min-w-0" key={collection.id}>
                    <CollectionManagementControl
                      collection={collection}
                      onDeleted={onDeleted}
                      onRenamed={onRenamed}
                    >
                      {(contextProps) => (
                        <CollectionButton
                          {...contextProps}
                          active={selectedId === collection.id}
                          count={collection.articleCount}
                          icon={selectedId === collection.id ? FolderOpen : Folder}
                          label={collection.name}
                          onClick={() => onSelect(collection.id)}
                        />
                      )}
                    </CollectionManagementControl>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </nav>

      </div>

      <NewCollectionDialog
        onClose={() => setDialogOpen(false)}
        onCreated={onCreated}
        open={dialogOpen}
      />
    </aside>
  )
}

function CollectionButton({
  active,
  count,
  icon: Icon,
  label,
  onClick,
  onContextMenu,
  onKeyDown,
  buttonRef,
  ...ariaProps
}: {
  active: boolean
  "aria-controls"?: string
  "aria-expanded"?: boolean
  "aria-haspopup"?: "menu"
  buttonRef?: React.Ref<HTMLButtonElement>
  count: number | null
  icon: typeof Folder
  label: string
  onClick: () => void
  onContextMenu?: React.MouseEventHandler<HTMLButtonElement>
  onKeyDown?: React.KeyboardEventHandler<HTMLButtonElement>
}) {
  return (
    <button
      aria-current={active ? "page" : undefined}
      {...ariaProps}
      className={cn(
        "flex min-h-11 w-full min-w-0 cursor-pointer items-center gap-2 rounded-lg px-2.5 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-accent font-medium text-accent-foreground"
          : "text-foreground hover:bg-muted",
      )}
      onClick={onClick}
      onContextMenu={onContextMenu}
      onKeyDown={onKeyDown}
      ref={buttonRef}
      type="button"
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate" title={label}>{label}</span>
      {count !== null ? (
        <span
          aria-label={`${formatNumber(count)} ${count === 1 ? "article" : "articles"}`}
          className="shrink-0 text-xs tabular-nums text-muted-foreground"
        >
          {formatNumber(count)}
        </span>
      ) : null}
    </button>
  )
}

function NewCollectionDialog({
  onClose,
  onCreated,
  open,
}: {
  onClose: () => void
  onCreated: (collection: ArticleCollection) => void
  open: boolean
}) {
  const [name, setName] = useState("")
  const [touched, setTouched] = useState(false)
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const trimmedName = name.trim()
  const validationError = trimmedName.length === 0
    ? "Enter a collection name."
    : trimmedName.length > 60
      ? "Collection name must be 60 characters or fewer."
      : null

  function close() {
    if (pending) return
    setName("")
    setTouched(false)
    setServerError(null)
    onClose()
  }

  useEditorialModal({
    open,
    containerRef: dialogRef,
    initialFocusRef: inputRef,
    onClose: close,
    canClose: !pending,
  })

  if (!open) return null

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setTouched(true)
    if (validationError || pending) return
    setPending(true)
    setServerError(null)
    try {
      const collection = await createArticleCollection(trimmedName)
      setPending(false)
      setName("")
      setTouched(false)
      onClose()
      onCreated(collection)
    } catch (cause) {
      setServerError(getApiErrorMessage(cause, "Collection could not be created"))
      setPending(false)
    }
  }

  const showValidation = touched && validationError

  return (
    <div
      aria-describedby="new-collection-description"
      aria-labelledby="new-collection-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <form className="w-full max-w-md space-y-5 rounded-xl border bg-background p-5 shadow-xl" onSubmit={submit}>
        <div>
          <h2 className="text-lg font-semibold" id="new-collection-title">New Collection</h2>
          <p className="mt-1 text-sm text-muted-foreground" id="new-collection-description">
            Group articles for focused reading and review.
          </p>
        </div>

        <label className="grid gap-1.5 text-sm font-medium" htmlFor="collection-name">
          Collection name
          <input
            aria-label="Collection name"
            aria-describedby={`collection-name-help${showValidation ? " collection-name-error" : ""}`}
            aria-invalid={showValidation ? true : undefined}
            autoComplete="off"
            className="min-h-11 w-full rounded-lg border bg-background px-3 text-base"
            disabled={pending}
            id="collection-name"
            maxLength={80}
            onBlur={(event) => {
              if (event.relatedTarget !== cancelRef.current) setTouched(true)
            }}
            onChange={(event) => {
              setName(event.target.value)
              setServerError(null)
            }}
            ref={inputRef}
            value={name}
          />
          <span className="flex justify-between gap-3 text-xs font-normal text-muted-foreground" id="collection-name-help">
            <span>1–60 characters</span>
            <span aria-label={`${trimmedName.length} of 60 characters`}>{trimmedName.length}/60</span>
          </span>
        </label>

        {showValidation ? (
          <p className="text-sm text-red-700" id="collection-name-error" role="alert">{validationError}</p>
        ) : null}
        {serverError ? <p className="text-sm text-red-700" dir="auto" role="alert">{serverError}</p> : null}

        <div className="flex justify-end gap-2">
          <Button disabled={pending} onClick={close} ref={cancelRef} type="button" variant="outline">Cancel</Button>
          <Button disabled={Boolean(validationError) || pending} type="submit">
            {pending ? "Creating…" : "Create collection"}
          </Button>
        </div>
      </form>
    </div>
  )
}
