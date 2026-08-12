"use client"

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table"
import { ChevronLeft, ChevronRight, LoaderCircle, RefreshCw, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { StatusBadge, statusLabels } from "@/components/dashboard/status-badge"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatNumber } from "@/lib/format"
import { formatInTimeZone } from "@/lib/date-time"
import { cn } from "@/lib/utils"
import type {
  SourcePlatform,
  SourceSummary,
} from "@/features/operations/ingestion-types"

type SourceHealthTableProps = {
  bulkChecking?: boolean
  checkingSourceIds?: ReadonlySet<string>
  sources: SourceSummary[]
  selectedSourceId: string
  onCheckAll?: () => void
  onCheckSource?: (sourceId: string) => void
  onDeleteSource?: (source: SourceSummary) => void
  onSelectSource: (sourceId: string) => void
  totalCount?: number
  pageOffset?: number
  pageSize?: number
  hasMore?: boolean
  onPageChange?: (offset: number) => void
}

const filters: { label: string; value: "all" | SourcePlatform }[] = [
  { label: "All", value: "all" },
  { label: "RSS", value: "rss" },
  { label: "Atom", value: "atom" },
  { label: "Telegram", value: "telegram_public" },
]

const nestedInteractiveControlSelector = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "summary",
  "[contenteditable='true']",
  "[role='button']",
  "[role='checkbox']",
  "[role='combobox']",
  "[role='link']",
  "[role='menuitem']",
  "[role='menuitemcheckbox']",
  "[role='menuitemradio']",
  "[role='option']",
  "[role='radio']",
  "[role='slider']",
  "[role='spinbutton']",
  "[role='switch']",
  "[role='textbox']",
].join(",")

export function SourceHealthTable({
  bulkChecking = false,
  checkingSourceIds = new Set(),
  sources,
  selectedSourceId,
  onCheckAll,
  onCheckSource,
  onDeleteSource,
  onSelectSource,
  totalCount,
  pageOffset = 0,
  pageSize = 50,
  hasMore = false,
  onPageChange,
}: SourceHealthTableProps) {
  const { timezone } = useDateTime()
  const [filter, setFilter] = useState<"all" | SourcePlatform>("all")
  const visibleSources = useMemo(
    () => filter === "all" ? sources : sources.filter((source) => source.platform === filter),
    [filter, sources]
  )
  const counts = {
    all: sources.length,
    rss: sources.filter((source) => source.platform === "rss").length,
    atom: sources.filter((source) => source.platform === "atom").length,
    telegram: sources.filter((source) => source.platform === "telegram_public").length,
  }

  const columns = useMemo<ColumnDef<SourceSummary>[]>(
    () => [
      {
        id: "type",
        header: "Type",
        cell: ({ row }) => (
          <SourceIcon
            iconUrl={row.original.iconUrl}
            iconUpdatedAt={row.original.iconUpdatedAt}
            name={row.original.name}
            platform={row.original.platform}
            sourceId={row.original.id}
          />
        ),
      },
      {
        id: "source",
        header: "Source",
        cell: ({ row }) => (
          <div className="w-full min-w-0 text-left">
            <div className="truncate font-medium">{row.original.name}</div>
            <div className="truncate text-xs text-muted-foreground">{row.original.url}</div>
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => {
          const source = row.original
          const checking = checkingSourceIds.has(source.id)
          return (
            <div className="min-w-0">
              {onCheckSource ? (
                <button
                  aria-label={
                    checking
                      ? `Checking ${source.name} health`
                      : `Check ${source.name} health, currently ${statusLabels[source.status]}`
                  }
                  className="min-h-11 rounded-md py-1 outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-wait"
                  disabled={checking || source.status === "disabled"}
                  onClick={(event) => {
                    event.stopPropagation()
                    onCheckSource(source.id)
                  }}
                  title={source.failureReason ?? `Last checked: ${formatCheckedAt(source.lastCheckedAt, timezone)}`}
                  type="button"
                >
                  {checking ? (
                    <span className="inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-xs font-medium text-muted-foreground">
                      <LoaderCircle className="size-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                      Checking
                    </span>
                  ) : (
                    <StatusBadge status={source.status} />
                  )}
                </button>
              ) : (
                <StatusBadge status={source.status} />
              )}
              {source.lastCheckedAt ? (
                <div className="mt-1 hidden truncate text-[11px] text-muted-foreground sm:block">
                  Last checked {formatCheckedAt(source.lastCheckedAt, timezone)}
                </div>
              ) : null}
              {source.failureReason ? (
                <div className="mt-0.5 truncate text-[11px] text-destructive" title={source.failureReason}>
                  {source.failureReason}
                </div>
              ) : null}
            </div>
          )
        },
      },
      {
        id: "items",
        header: "Items",
        cell: ({ row }) => <span className="tabular-nums">{formatNumber(row.original.items24h)}</span>,
      },
      {
        id: "failed",
        header: "Failed",
        cell: ({ row }) => <span className="text-destructive tabular-nums">{formatNumber(row.original.failed24h)}</span>,
      },
      {
        id: "lastSuccess",
        header: "Last success",
        cell: ({ row }) => row.original.lastSuccess ? formatInTimeZone(row.original.lastSuccess, timezone) : "-",
      },
      {
        header: "",
        id: "actions",
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1">
            {onDeleteSource ? (
              <Button
                aria-label={`Delete ${row.original.name}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onDeleteSource(row.original)
                }}
                className="size-11 min-h-11 min-w-11 text-destructive hover:bg-[var(--error-surface)] hover:text-destructive"
                type="button"
                variant="ghost"
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            ) : null}
          </div>
        ),
      },
    ],
    [checkingSourceIds, onCheckSource, onDeleteSource, onSelectSource, timezone]
  )

  const table = useReactTable({
    data: visibleSources,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <Card className="rounded-md py-0" size="sm">
      <CardHeader className="flex-row flex-wrap items-center gap-2 border-b px-3 py-2">
        <CardTitle className="text-base">
          {onCheckAll ? (
            <Button
              aria-label={bulkChecking ? "Checking all source health" : "Check all source health"}
              className="h-9 gap-2 px-2"
              disabled={bulkChecking || sources.length === 0}
              onClick={onCheckAll}
              type="button"
              variant="ghost"
            >
              {bulkChecking ? (
                <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <RefreshCw className="size-4" aria-hidden="true" />
              )}
              {bulkChecking ? "Checking source health" : "Source health"}
            </Button>
          ) : (
            "Source health"
          )}
        </CardTitle>
        <div className="ml-auto min-w-0 max-w-full">
          <div role="tablist" aria-label="Source platform filter" className="flex max-w-full items-center gap-1 overflow-x-auto">
            {filters.map((item) => {
              const total = item.value === "all"
                ? counts.all
                : item.value === "rss"
                  ? counts.rss
                  : item.value === "atom"
                    ? counts.atom
                    : counts.telegram
              return (
                <button
                  key={item.value}
                  type="button"
                  role="tab"
                  aria-selected={filter === item.value}
                  tabIndex={filter === item.value ? 0 : -1}
                  onClick={() => setFilter(item.value)}
                  className={cn(
                    "min-h-11 shrink-0 rounded-md border px-2.5 text-[13px] text-muted-foreground transition min-[900px]:min-h-8",
                    filter === item.value && "border-primary/30 bg-accent text-accent-foreground"
                  )}
                >
                  {item.label} <span className="ml-1 tabular-nums">{total}</span>
                </button>
              )
            })}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-0">
        <Table className="table-fixed">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className={cn("h-9 whitespace-nowrap px-2 text-xs", columnClassName(header.column.id))}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.original.id === selectedSourceId ? "selected" : undefined}
                  onDoubleClick={(event) => {
                    if (isNestedInteractiveControl(event.target)) return
                    onSelectSource(row.original.id)
                  }}
                  className="h-11 cursor-pointer transition-colors hover:bg-black/[0.03] data-[state=selected]:bg-black/5 dark:hover:bg-white/[0.03] dark:data-[state=selected]:bg-white/5"
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cn("overflow-hidden px-2 py-2 text-sm", columnClassName(cell.column.id))}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-20 px-2 text-center text-sm text-muted-foreground">
                  No sources found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <div className="flex min-h-9 items-center justify-between gap-2 border-t px-3 text-sm text-muted-foreground">
          <span>
            {totalCount !== undefined && totalCount !== counts.all
              ? `Showing ${totalCount === 0 ? 0 : pageOffset + 1}–${Math.min(pageOffset + visibleSources.length, totalCount)} of ${totalCount}`
              : `Showing ${visibleSources.length} of ${counts.all}`}
          </span>
          {onPageChange && totalCount !== undefined && totalCount > pageSize ? (
            <div className="flex items-center gap-1">
              <Button
                aria-label="Previous source page"
                disabled={pageOffset === 0}
                onClick={() => onPageChange(Math.max(0, pageOffset - pageSize))}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                <ChevronLeft className="size-4" aria-hidden="true" />
              </Button>
              <Button
                aria-label="Next source page"
                disabled={!hasMore}
                onClick={() => onPageChange(pageOffset + pageSize)}
                size="icon-xs"
                type="button"
                variant="ghost"
              >
                <ChevronRight className="size-4" aria-hidden="true" />
              </Button>
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function columnClassName(columnId: string) {
  switch (columnId) {
    case "type":
      return "hidden w-11 min-[480px]:table-cell"
    case "source":
      return "w-auto min-w-0"
    case "status":
      return "w-32 sm:w-36"
    case "items":
    case "failed":
      return "hidden w-16 text-right sm:table-cell"
    case "lastSuccess":
      return "hidden w-28 2xl:table-cell"
    case "actions":
      return "w-14 text-right"
    default:
      return ""
  }
}

function isNestedInteractiveControl(target: EventTarget | null) {
  return target instanceof Element && target.closest(nestedInteractiveControlSelector) !== null
}

function formatCheckedAt(value: string | null | undefined, timezone: string) {
  if (!value) return "never"
  return formatInTimeZone(value, timezone, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}
