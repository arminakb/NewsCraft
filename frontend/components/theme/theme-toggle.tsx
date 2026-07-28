"use client"

import { Moon, Sun } from "lucide-react"
import { useId } from "react"

import { useTheme } from "@/components/providers/theme-provider"
import { cn } from "@/lib/utils"

export function ThemeToggle({ placement }: { placement: "sidebar" | "mobile" }) {
  const { theme, toggleTheme } = useTheme()
  const tooltipId = useId()
  const nextTheme = theme === "dark" ? "light" : "dark"
  const tooltip = `Switch to ${nextTheme} theme`

  return (
    <div className="group/theme relative">
      <button
        aria-describedby={tooltipId}
        aria-label="Toggle color theme"
        aria-pressed={theme === "dark"}
        className={cn(
          "grid size-11 place-items-center rounded-[7px] text-muted-foreground transition-colors duration-200 hover:bg-navigation-hover hover:text-foreground active:bg-navigation-active focus-visible:ring-2 focus-visible:ring-ring/60",
          placement === "mobile" && "shrink-0",
        )}
        onClick={toggleTheme}
        title={tooltip}
        type="button"
      >
        <Moon className="size-[17px] dark:hidden" aria-hidden="true" strokeWidth={1.5} />
        <Sun className="hidden size-[17px] dark:block" aria-hidden="true" strokeWidth={1.5} />
      </button>
      <span
        className={cn(
          "pointer-events-none invisible absolute z-50 w-max rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background opacity-0 shadow-sm transition-opacity duration-150 group-hover/theme:visible group-hover/theme:opacity-100 group-focus-within/theme:visible group-focus-within/theme:opacity-100",
          placement === "sidebar"
            ? "left-[calc(100%+0.5rem)] top-1/2 -translate-y-1/2"
            : "right-0 top-[calc(100%+0.5rem)]",
        )}
        id={tooltipId}
        role="tooltip"
      >
        {tooltip}
      </span>
    </div>
  )
}
