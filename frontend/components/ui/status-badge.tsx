import { Circle } from "lucide-react"
import type React from "react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type StatusTone = "error" | "info" | "neutral" | "success" | "warning"

const variants: Record<StatusTone, "default" | "error" | "neutral" | "success" | "warning"> = {
  error: "error",
  info: "default",
  neutral: "neutral",
  success: "success",
  warning: "warning",
}

const dotClasses: Record<StatusTone, string> = {
  error: "fill-destructive text-destructive",
  info: "fill-primary-solid-foreground text-primary-solid-foreground",
  neutral: "fill-muted-foreground text-muted-foreground",
  success: "fill-success text-success",
  warning: "fill-warning text-warning",
}

function StatusBadge({
  tone,
  children,
  className,
}: {
  tone: StatusTone
  children: React.ReactNode
  className?: string
}) {
  return (
    <Badge variant={variants[tone]} className={cn("gap-1.5", className)}>
      <Circle className={cn("size-1.5", dotClasses[tone])} aria-hidden="true" />
      {children}
    </Badge>
  )
}

export { StatusBadge, type StatusTone }
