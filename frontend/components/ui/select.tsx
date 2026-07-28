import * as React from "react"

import { controlClassName } from "@/components/ui/input"
import { cn } from "@/lib/utils"

function Select({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(controlClassName, "cursor-pointer pe-8", className)}
      {...props}
    />
  )
}

export { Select }
