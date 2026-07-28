import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-md border border-transparent px-2 py-0.5 text-[11px] font-medium whitespace-nowrap transition-colors duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3! [&>svg]:stroke-[1.5]",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "border-destructive/30 bg-[var(--error-surface)] text-destructive focus-visible:ring-destructive forced-colors:border-[CanvasText] forced-colors:text-[CanvasText] [a]:hover:bg-destructive/15",
        error:
          "border-destructive/30 bg-[var(--error-surface)] text-destructive focus-visible:ring-destructive forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        warning:
          "border-warning/30 bg-[var(--warning-surface)] text-warning focus-visible:ring-warning forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        success:
          "border-success/30 bg-[var(--success-surface)] text-success focus-visible:ring-success forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        neutral:
          "border-border/70 bg-muted text-muted-foreground focus-visible:ring-ring forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }
