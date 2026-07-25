"use client"

import { Check, LoaderCircle, Plus } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"

import {
  createArticleCollection,
  removeArticleFromCollection,
  saveArticleToCollection,
} from "./api"
import type { ArticleCollection, ArticleSummary } from "./types"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import { Button } from "@/components/ui/button"
import { formatNumber } from "@/lib/format"
import { getApiErrorMessage } from "@/lib/http"
import { cn } from "@/lib/utils"

type SaveToCollectionDialogProps = {
  article: ArticleSummary | null
  collections: ArticleCollection[] | undefined
  collectionsError: unknown
  collectionsPending: boolean
  onClose: () => void
  onCollectionCreated: (collection: ArticleCollection) => void
  onPendingChange: (pending: boolean) => void
  onReconcile: (articleId: string, confirmedCollectionIds: string[]) => Promise<string[]>
  onRetryCollections: () => void
  onSaved: (collectionCount: number) => void
  open: boolean
}

export function SaveToCollectionDialog({
  article,
  collections,
  collectionsError,
  collectionsPending,
  onClose,
  onCollectionCreated,
  onPendingChange,
  onReconcile,
  onRetryCollections,
  onSaved,
  open,
}: SaveToCollectionDialogProps) {
  const [baseline, setBaseline] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pending, setPending] = useState(false)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [name, setName] = useState("")
  const [nameTouched, setNameTouched] = useState(false)
  const [createPending, setCreatePending] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const firstCheckboxRef = useRef<HTMLInputElement>(null)
  const createInputRef = useRef<HTMLInputElement>(null)
  const busyRef = useRef(false)
  const nameId = useId()
  const busy = pending || createPending
  const trimmedName = name.trim()
  const nameError = trimmedName.length === 0
    ? "Enter a collection name."
    : trimmedName.length > 60
      ? "Collection name must be 60 characters or fewer."
      : null

  useEffect(() => {
    if (!open || !article) return
    const memberships = new Set(article.savedCollectionIds)
    setBaseline(memberships)
    setSelected(new Set(memberships))
    setMutationError(null)
    setName("")
    setNameTouched(false)
    setCreateError(null)
  }, [article, open])

  useEffect(() => {
    if (!open || collectionsPending || collectionsError || !collections) return
    const available = new Set(collections.map((collection) => collection.id))
    setBaseline((current) => new Set([...current].filter((id) => available.has(id))))
    setSelected((current) => new Set([...current].filter((id) => available.has(id))))
  }, [collections, collectionsError, collectionsPending, open])

  function close() {
    if (busy || busyRef.current) return
    onClose()
  }

  useEditorialModal({
    open,
    containerRef: dialogRef,
    initialFocusRef: collections?.length ? firstCheckboxRef : createInputRef,
    onClose: close,
    canClose: !busy,
  })

  if (!open || !article) return null
  const activeArticle = article

  function toggleCollection(collectionId: string) {
    if (busy) return
    setMutationError(null)
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(collectionId)) next.delete(collectionId)
      else next.add(collectionId)
      return next
    })
  }

  async function apply() {
    if (busy || busyRef.current || collectionsPending || collectionsError) return
    busyRef.current = true
    setPending(true)
    onPendingChange(true)
    setMutationError(null)
    const additions = [...selected].filter((id) => !baseline.has(id))
    const removals = [...baseline].filter((id) => !selected.has(id))
    const changes = [
      ...additions.map((collectionId) => ({ collectionId, kind: "add" as const })),
      ...removals.map((collectionId) => ({ collectionId, kind: "remove" as const })),
    ]
    const results = await Promise.allSettled(changes.map((change) => (
      change.kind === "add"
        ? saveArticleToCollection(change.collectionId, activeArticle.id)
        : removeArticleFromCollection(change.collectionId, activeArticle.id)
    )))
    const confirmed = new Set(baseline)
    results.forEach((result, index) => {
      if (result.status !== "fulfilled") return
      const change = changes[index]
      if (change.kind === "add") confirmed.add(change.collectionId)
      else confirmed.delete(change.collectionId)
    })

    try {
      const reconciledIds = await onReconcile(activeArticle.id, [...confirmed])
      const reconciled = new Set(reconciledIds)
      setBaseline(reconciled)
      setSelected(new Set(reconciled))
      if (results.some((result) => result.status === "rejected")) {
        const firstFailure = results.find((result) => result.status === "rejected")
        const detail = firstFailure?.status === "rejected"
          ? getApiErrorMessage(firstFailure.reason, "A collection change failed")
          : "A collection change failed"
        setMutationError(`Some changes could not be saved: ${detail}. Confirmed memberships were reloaded. Review them and try again.`)
      } else {
        onSaved(reconciled.size)
        onClose()
      }
    } catch (cause) {
      setBaseline(confirmed)
      setSelected(new Set(confirmed))
      setMutationError(getApiErrorMessage(cause, "Changes may have saved, but the Feed could not be refreshed. Review and try again."))
    } finally {
      busyRef.current = false
      setPending(false)
      onPendingChange(false)
    }
  }

  async function createCollection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNameTouched(true)
    if (nameError || busy || busyRef.current) return
    busyRef.current = true
    setCreatePending(true)
    setCreateError(null)
    try {
      const collection = await createArticleCollection(trimmedName)
      onCollectionCreated(collection)
      setSelected((current) => new Set(current).add(collection.id))
      setName("")
      setNameTouched(false)
      queueMicrotask(() => firstCheckboxRef.current?.focus())
    } catch (cause) {
      setCreateError(getApiErrorMessage(cause, "Collection could not be created"))
    } finally {
      busyRef.current = false
      setCreatePending(false)
    }
  }

  const showNameError = nameTouched && nameError

  return (
    <div
      aria-describedby="save-to-collection-description"
      aria-labelledby="save-to-collection-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close()
      }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <div className="flex max-h-[min(760px,calc(100vh-2rem))] w-full max-w-lg flex-col overflow-hidden rounded-xl border bg-background shadow-xl">
        <header className="border-b px-5 py-4">
          <h2 className="text-lg font-semibold" id="save-to-collection-title">Save to Collection</h2>
          <p className="mt-1 text-sm text-muted-foreground" id="save-to-collection-description">
            Choose one or more collections for this article.
          </p>
          <DirectionBoundary
            as="p"
            className="mt-2 line-clamp-2 text-sm font-medium"
            direction={article.direction}
            language={article.language}
          >
            {article.title ?? "Untitled article"}
          </DirectionBoundary>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {collectionsPending ? (
            <div aria-label="Loading collections for article" className="space-y-2" role="status">
              <span className="sr-only">Loading collections</span>
              {[0, 1, 2].map((item) => <div aria-hidden="true" className="h-11 animate-pulse rounded-lg bg-muted" key={item} />)}
            </div>
          ) : null}

          {collectionsError ? (
            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm text-red-700" dir="auto" role="alert">
                {getApiErrorMessage(collectionsError, "Collections could not be loaded")}
              </p>
              <Button onClick={onRetryCollections} size="sm" variant="outline">Retry</Button>
            </div>
          ) : null}

          {!collectionsPending && !collectionsError && collections?.length ? (
            <fieldset className="space-y-2" disabled={busy}>
              <legend className="sr-only">Collections</legend>
              {collections.map((collection, index) => (
                <label
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 transition-colors",
                    selected.has(collection.id) ? "border-primary/40 bg-primary/5" : "hover:bg-muted/60",
                    busy && "cursor-not-allowed opacity-60",
                  )}
                  key={collection.id}
                >
                  <input
                    checked={selected.has(collection.id)}
                    className="size-4 accent-primary"
                    onChange={() => toggleCollection(collection.id)}
                    ref={index === 0 ? firstCheckboxRef : undefined}
                    type="checkbox"
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium" title={collection.name}>{collection.name}</span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {formatNumber(collection.articleCount)} {collection.articleCount === 1 ? "article" : "articles"}
                  </span>
                  {selected.has(collection.id) ? <Check className="size-4 text-primary" aria-hidden="true" /> : null}
                </label>
              ))}
            </fieldset>
          ) : null}

          {!collectionsPending && !collectionsError && collections?.length === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-center">
              <p className="font-medium">No collections yet</p>
              <p className="mt-1 text-sm text-muted-foreground">Create one below to save this article.</p>
            </div>
          ) : null}

          {mutationError ? (
            <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
              {mutationError}
            </p>
          ) : null}

          {!collectionsPending && !collectionsError ? (
            <form className="mt-5 border-t pt-4" onSubmit={createCollection}>
              <label className="text-sm font-medium" htmlFor={nameId}>Create a collection</label>
              <div className="mt-1.5 flex gap-2">
                <input
                  aria-describedby={showNameError ? `${nameId}-error` : undefined}
                  aria-invalid={showNameError ? true : undefined}
                  autoComplete="off"
                  className="min-h-11 min-w-0 flex-1 rounded-lg border bg-background px-3 text-base"
                  disabled={busy}
                  id={nameId}
                  maxLength={80}
                  onBlur={() => setNameTouched(true)}
                  onChange={(event) => {
                    setName(event.target.value)
                    setCreateError(null)
                  }}
                  placeholder="Collection name"
                  ref={createInputRef}
                  value={name}
                />
                <Button disabled={Boolean(nameError) || busy} type="submit" variant="outline">
                  {createPending ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <Plus className="size-4" aria-hidden="true" />}
                  {createPending ? "Creating…" : "Create"}
                </Button>
              </div>
              {showNameError ? <p className="mt-1.5 text-sm text-red-700" id={`${nameId}-error`} role="alert">{nameError}</p> : null}
              {createError ? <p className="mt-1.5 text-sm text-red-700" dir="auto" role="alert">{createError}</p> : null}
            </form>
          ) : null}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t bg-muted/20 px-5 py-4">
          <Button disabled={busy} onClick={close} type="button" variant="outline">Cancel</Button>
          <Button disabled={busy || collectionsPending || Boolean(collectionsError)} onClick={apply} type="button">
            {pending ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : null}
            {pending ? "Applying…" : "Apply"}
          </Button>
        </footer>
      </div>
    </div>
  )
}
