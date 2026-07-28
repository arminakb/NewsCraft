import * as React from "react"

import { controlClassName } from "@/components/ui/input"
import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(controlClassName, "min-h-24 resize-y", className)}
      {...props}
    />
  )
}

export { Textarea }
