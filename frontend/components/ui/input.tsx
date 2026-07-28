import * as React from "react"

import { cn } from "@/lib/utils"

const controlClassName =
  "min-h-11 w-full min-w-0 rounded-lg border border-input bg-card px-3 py-2 text-base text-foreground shadow-xs outline-none transition-[border-color,box-shadow,background-color] duration-150 placeholder:text-muted-foreground/80 hover:border-foreground/25 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:opacity-65 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 min-[900px]:min-h-9 min-[900px]:text-[13px]"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      data-slot="input"
      type={type}
      className={cn(controlClassName, className)}
      {...props}
    />
  )
}

export { Input, controlClassName }
