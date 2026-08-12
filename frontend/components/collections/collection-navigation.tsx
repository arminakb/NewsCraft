import type { LucideIcon } from "lucide-react"
import type { Ref } from "react"

import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

export function CollectionNavigationItem({
  active,
  buttonRef,
  count,
  countLabel,
  icon: Icon,
  label,
  onClick,
  onContextMenu,
  onKeyDown,
  status,
  ...ariaProps
}: {
  active: boolean
  "aria-controls"?: string
  "aria-expanded"?: boolean
  "aria-haspopup"?: "menu"
  buttonRef?: Ref<HTMLButtonElement>
  count: number | null
  countLabel: (count: number) => string
  icon: LucideIcon
  label: string
  onClick: () => void
  onContextMenu?: React.MouseEventHandler<HTMLButtonElement>
  onKeyDown?: React.KeyboardEventHandler<HTMLButtonElement>
  status?: React.ReactNode
}) {
  return (
    <div className="group/collection flex min-w-0 items-center gap-1">
      <button
        aria-current={active ? "page" : undefined}
        {...ariaProps}
        className={cn(
          "flex min-h-11 w-auto min-w-32 flex-1 cursor-pointer items-center gap-2 rounded-lg px-2.5 text-left text-sm outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring min-[900px]:w-full min-[900px]:min-w-0",
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
        {status}
        {count !== null ? (
          <span
            aria-label={countLabel(count)}
            className="shrink-0 text-xs tabular-nums text-muted-foreground"
          >
            {formatNumber(count)}
          </span>
        ) : null}
      </button>
    </div>
  )
}
