"use client"

import { Moon, Sun } from "lucide-react"
import { useId } from "react"

import { useTheme } from "@/components/providers/theme-provider"
import { cn } from "@/lib/utils"

export function ThemeToggle({
  expanded = false,
  placement,
}: {
  expanded?: boolean
  placement: "sidebar" | "mobile"
}) {
  const { theme, toggleTheme } = useTheme()
  const tooltipId = useId()
  const nextTheme = theme === "dark" ? "light" : "dark"
  const tooltip = `Switch to ${nextTheme} theme`
  const showSidebarLabel = placement === "sidebar" && expanded
  const showTooltip = placement === "mobile" || !showSidebarLabel

  return (
    <div className="group/theme relative">
      <button
        aria-describedby={showTooltip ? tooltipId : undefined}
        aria-label="Toggle color theme"
        aria-pressed={theme === "dark"}
        className={cn(
          "flex min-h-11 min-w-11 items-center rounded-[7px] text-[13px] font-medium text-muted-foreground transition-[background-color,color,padding,gap] duration-[180ms] hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
          showSidebarLabel ? "w-full justify-start gap-2.5 px-2.5" : "justify-center",
          placement === "mobile" && "shrink-0",
        )}
        onClick={toggleTheme}
        title={tooltip}
        type="button"
      >
        <span className="grid size-[18px] shrink-0 place-items-center">
          <Moon className="size-[17px] dark:hidden" aria-hidden="true" strokeWidth={1.5} />
          <Sun className="hidden size-[17px] dark:block" aria-hidden="true" strokeWidth={1.5} />
        </span>
        {placement === "sidebar" ? (
          <span
            aria-hidden={!showSidebarLabel}
            className={cn(
              "overflow-hidden whitespace-nowrap transition-[max-width,opacity,transform] duration-150 motion-reduce:transition-none",
              showSidebarLabel
                ? "max-w-40 translate-x-0 opacity-100 delay-75"
                : "max-w-0 -translate-x-1 opacity-0",
            )}
          >
            Theme
          </span>
        ) : null}
      </button>
      {showTooltip ? (
        <span
          className={cn(
            "pointer-events-none invisible absolute z-50 w-max rounded-md border border-border/50 bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground opacity-0 shadow-md transition-opacity duration-150 group-hover/theme:visible group-hover/theme:opacity-100 group-focus-within/theme:visible group-focus-within/theme:opacity-100 motion-reduce:transition-none",
            placement === "sidebar"
              ? "left-[calc(100%+0.5rem)] top-1/2 -translate-y-1/2"
              : "right-0 top-[calc(100%+0.5rem)]",
          )}
          id={tooltipId}
          role="tooltip"
        >
          {tooltip}
        </span>
      ) : null}
    </div>
  )
}
