"use client"

import { Filter, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { EMPTY_ARTICLE_FILTERS, activeFilterCount } from "./filter-state"
import type { ArticleFacetValue, ArticleFacets, ArticleFilters, ArticleSourceFacet } from "./types"

import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { formatNumber, formatPlatform, titleCase } from "@/lib/format"
import { getApiErrorMessage } from "@/lib/http"
import { useMediaQuery } from "@/lib/use-media-query"

type FilterControlProps = {
  filters: ArticleFilters
  facets: ArticleFacets | undefined
  facetsPending: boolean
  facetsError: Error | null
  onRetryFacets: () => void
  onApply: (filters: ArticleFilters) => void
  onClear: () => void
}

export function ArticleFilterControl(props: FilterControlProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(props.filters)
  const [validationError, setValidationError] = useState<string | null>(null)
  const mobile = useMediaQuery("(max-width: 767px)")
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const count = activeFilterCount(props.filters)

  useEditorialModal({ open, containerRef: panelRef, initialFocusRef: closeRef, onClose: () => setOpen(false) })

  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!mobile && !panelRef.current?.contains(target) && !triggerRef.current?.contains(target)) setOpen(false)
    }
    document.addEventListener("pointerdown", closeOutside)
    return () => document.removeEventListener("pointerdown", closeOutside)
  }, [mobile, open])

  const show = () => {
    setDraft(props.filters)
    setValidationError(null)
    setOpen(true)
  }
  const apply = () => {
    const error = validateFilters(draft)
    if (error) {
      setValidationError(error)
      return
    }
    props.onApply(draft)
    setOpen(false)
  }
  const clear = () => {
    closeRef.current?.focus()
    setDraft(EMPTY_ARTICLE_FILTERS)
    setValidationError(null)
    props.onClear()
  }

  return (
    <div className="relative">
      <Button
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={count ? `Filter articles, ${count} active` : "Filter articles"}
        className="gap-2"
        onClick={show}
        ref={triggerRef}
        type="button"
        variant="outline"
      >
        <Filter aria-hidden="true" />
        Filter
        {count ? <span className="rounded-full bg-primary-solid px-1.5 py-0.5 text-[11px] leading-none text-primary-solid-foreground">{count}</span> : null}
      </Button>

      {open ? (
        <>
          <div
            aria-hidden="true"
            className="fixed inset-0 z-40 bg-black/40 md:hidden"
            onPointerDown={() => setOpen(false)}
          />
          <div
            aria-labelledby="article-filter-heading"
            aria-modal="true"
            className="nc-dialog fixed inset-x-0 bottom-0 z-50 max-h-[90dvh] overflow-y-auto rounded-b-none p-4 md:absolute md:inset-auto md:right-0 md:top-[calc(100%+0.5rem)] md:max-h-[calc(100dvh-10rem)] md:w-[430px] md:max-w-[calc(100vw-2rem)] md:rounded-xl md:p-5"
            ref={panelRef}
            role="dialog"
            tabIndex={-1}
          >
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold" id="article-filter-heading">Filter articles</h2>
                <p className="text-xs text-muted-foreground">Selections combine across groups.</p>
              </div>
              <Button aria-label="Close filters" onClick={() => setOpen(false)} ref={closeRef} size="icon" type="button" variant="ghost">
                <X aria-hidden="true" />
              </Button>
            </div>

            <div className="space-y-5 pb-16">
              <FacetFields
                draft={draft}
                error={props.facetsError}
                facets={props.facets}
                pending={props.facetsPending}
                retry={props.onRetryFacets}
                setDraft={setDraft}
              />

              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold">Has image</legend>
                <Select
                  aria-label="Has image"
                  onChange={(event) => setDraft({ ...draft, hasImage: event.target.value === "true" ? true : event.target.value === "false" ? false : null })}
                  value={draft.hasImage === null ? "any" : String(draft.hasImage)}
                >
                  <option value="any">Any</option>
                  <option value="true">Has image</option>
                  <option value="false">No image</option>
                </Select>
              </fieldset>

              <div className="grid grid-cols-2 gap-3">
                <NumberField label="Minimum score" value={draft.scoreMin} onChange={(scoreMin) => setDraft({ ...draft, scoreMin })} />
                <NumberField label="Maximum score" value={draft.scoreMax} onChange={(scoreMax) => setDraft({ ...draft, scoreMax })} />
                <DateField label="Date from" value={draft.dateFrom} onChange={(dateFrom) => setDraft({ ...draft, dateFrom })} />
                <DateField label="Date to" value={draft.dateTo} onChange={(dateTo) => setDraft({ ...draft, dateTo })} />
              </div>

              {validationError ? <p className="text-sm text-destructive" role="alert">{validationError}</p> : null}
            </div>

            <div className="sticky bottom-0 -mx-4 mt-5 flex gap-2 border-t bg-background px-4 pb-[max(0px,env(safe-area-inset-bottom))] pt-4 md:-mx-5 md:px-5">
              <Button className="flex-1" onClick={apply} type="button">Apply filters</Button>
              <Button disabled={count === 0 && activeFilterCount(draft) === 0} onClick={clear} type="button" variant="outline">Clear all</Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

function FacetFields({ draft, error, facets, pending, retry, setDraft }: {
  draft: ArticleFilters
  error: Error | null
  facets: ArticleFacets | undefined
  pending: boolean
  retry: () => void
  setDraft: (filters: ArticleFilters) => void
}) {
  if (pending) return <div aria-label="Loading filter options" className="rounded-lg border p-4 text-sm text-muted-foreground" role="status">Loading filter options…</div>
  if (error) return (
    <div className="space-y-2 rounded-lg border border-destructive/30 bg-[var(--error-surface)] p-3">
      <p className="text-sm text-destructive" dir="auto" role="alert">{getApiErrorMessage(error, "Filter options could not be loaded")}</p>
      <Button onClick={retry} size="sm" type="button" variant="outline">Retry options</Button>
    </div>
  )
  if (!facets) return null
  return (
    <>
      <CheckboxGroup label="Language" options={facets.languages} selected={draft.languages} onChange={(languages) => setDraft({ ...draft, languages })} format={(value) => value.toUpperCase()} />
      <CheckboxGroup label="Topic" options={facets.topics} selected={draft.topics} onChange={(topics) => setDraft({ ...draft, topics })} />
      <CheckboxGroup label="Content type" options={facets.contentTypes} selected={draft.contentTypes} onChange={(contentTypes) => setDraft({ ...draft, contentTypes })} />
      <SourceGroup options={facets.sources} selected={draft.sourceIds} onChange={(sourceIds) => setDraft({ ...draft, sourceIds })} />
      <CheckboxGroup label="Coverage" options={facets.coverage} selected={draft.coverage} onChange={(coverage) => setDraft({ ...draft, coverage: coverage as ArticleFilters["coverage"] })} format={titleCase} />
    </>
  )
}

function CheckboxGroup({ label, options, selected, onChange, format = (value) => value }: {
  label: string
  options: ArticleFacetValue[]
  selected: string[]
  onChange: (values: string[]) => void
  format?: (value: string) => string
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-semibold">{label}</legend>
      <div className="grid max-h-32 grid-cols-2 gap-1 overflow-y-auto rounded-lg border p-1.5">
        {options.map((option) => (
          <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md px-2 text-sm hover:bg-muted md:min-h-9" key={option.value}>
            <input
              checked={selected.includes(option.value)}
              className="size-4 accent-primary"
              onChange={() => onChange(toggle(selected, option.value))}
              type="checkbox"
            />
            <span className="min-w-0 flex-1 truncate">{format(option.value)}</span>
            <span className="text-xs tabular-nums text-muted-foreground">{formatNumber(option.count)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function SourceGroup({ options, selected, onChange }: { options: ArticleSourceFacet[]; selected: string[]; onChange: (values: string[]) => void }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-semibold">Source</legend>
      <div className="max-h-36 space-y-1 overflow-y-auto rounded-lg border p-1.5">
        {options.map((option) => (
          <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md px-2 text-sm hover:bg-muted md:min-h-9" key={option.id}>
            <input checked={selected.includes(option.id)} className="size-4 accent-primary" onChange={() => onChange(toggle(selected, option.id))} type="checkbox" />
            <span className="min-w-0 flex-1 truncate">{option.name} <span className="text-muted-foreground">· {formatPlatform(option.platform)}</span></span>
            <span className="text-xs tabular-nums text-muted-foreground">{formatNumber(option.count)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function NumberField({ label, value, onChange }: { label: string; value: number | null; onChange: (value: number | null) => void }) {
  return (
    <label className="grid gap-1 text-sm font-medium">
      {label}
      <Input
        inputMode="numeric"
        onChange={(event) => onChange(event.target.value === "" || !Number.isInteger(event.target.valueAsNumber) ? null : event.target.valueAsNumber)}
        step="1"
        type="number"
        value={value ?? ""}
      />
    </label>
  )
}

function DateField({ label, value, onChange }: { label: string; value: string | null; onChange: (value: string | null) => void }) {
  return (
    <label className="grid gap-1 text-sm font-medium">
      {label}
      <Input onChange={(event) => onChange(event.target.value || null)} type="date" value={value ?? ""} />
    </label>
  )
}

export function ActiveFilterChips({ filters, facets, onChange, onClear }: {
  filters: ArticleFilters
  facets: ArticleFacets | undefined
  onChange: (filters: ArticleFilters) => void
  onClear: () => void
}) {
  const chips: Array<{ key: string; label: string; remove: () => ArticleFilters }> = []
  for (const value of filters.languages) chips.push({ key: `language:${value}`, label: value.toUpperCase(), remove: () => ({ ...filters, languages: filters.languages.filter((item) => item !== value) }) })
  for (const value of filters.topics) chips.push({ key: `topic:${value}`, label: value, remove: () => ({ ...filters, topics: filters.topics.filter((item) => item !== value) }) })
  for (const value of filters.contentTypes) chips.push({ key: `type:${value}`, label: titleCase(value), remove: () => ({ ...filters, contentTypes: filters.contentTypes.filter((item) => item !== value) }) })
  for (const value of filters.sourceIds) chips.push({ key: `source:${value}`, label: facets?.sources.find((source) => source.id === value)?.name ?? value, remove: () => ({ ...filters, sourceIds: filters.sourceIds.filter((item) => item !== value) }) })
  for (const value of filters.coverage) chips.push({ key: `coverage:${value}`, label: titleCase(value), remove: () => ({ ...filters, coverage: filters.coverage.filter((item) => item !== value) }) })
  if (filters.hasImage !== null) chips.push({ key: "has-image", label: filters.hasImage ? "Has image" : "No image", remove: () => ({ ...filters, hasImage: null }) })
  if (filters.scoreMin !== null) chips.push({ key: "score-min", label: `Score ≥ ${filters.scoreMin}`, remove: () => ({ ...filters, scoreMin: null }) })
  if (filters.scoreMax !== null) chips.push({ key: "score-max", label: `Score ≤ ${filters.scoreMax}`, remove: () => ({ ...filters, scoreMax: null }) })
  if (filters.dateFrom) chips.push({ key: "date-from", label: `From ${filters.dateFrom}`, remove: () => ({ ...filters, dateFrom: null }) })
  if (filters.dateTo) chips.push({ key: "date-to", label: `To ${filters.dateTo}`, remove: () => ({ ...filters, dateTo: null }) })
  if (!chips.length) return null
  return (
    <div aria-label="Active filters" className="flex flex-wrap items-center gap-2">
      {chips.map((chip) => (
        <button
          aria-label={`Remove filter ${chip.label}`}
          className="inline-flex min-h-11 cursor-pointer items-center gap-1 rounded-full border bg-muted px-3 text-xs font-medium transition-colors hover:bg-muted/70 focus-visible:ring-2 focus-visible:ring-ring md:min-h-8"
          key={chip.key}
          onClick={() => onChange(chip.remove())}
          type="button"
        >
          {chip.label}<X aria-hidden="true" className="size-3" />
        </button>
      ))}
      <Button className="min-h-11 rounded-full px-3 text-xs md:min-h-8" onClick={onClear} size="sm" type="button" variant="ghost">
        Clear all
      </Button>
    </div>
  )
}

function toggle(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

function validateFilters(filters: ArticleFilters) {
  if (filters.scoreMin !== null && filters.scoreMax !== null && filters.scoreMin > filters.scoreMax) return "Minimum score must not exceed maximum score."
  if (filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo) return "Date from must not be later than date to."
  return null
}
