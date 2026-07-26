import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "border-red-300 bg-red-100 text-red-900 focus-visible:ring-red-700 dark:border-red-700 dark:bg-red-950 dark:text-red-100 dark:focus-visible:ring-red-300 forced-colors:border-[CanvasText] forced-colors:text-[CanvasText] [a]:hover:bg-red-200 dark:[a]:hover:bg-red-900",
        error:
          "border-red-300 bg-red-100 text-red-900 focus-visible:ring-red-700 dark:border-red-700 dark:bg-red-950 dark:text-red-100 dark:focus-visible:ring-red-300 forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        warning:
          "border-amber-300 bg-amber-100 text-amber-950 focus-visible:ring-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100 dark:focus-visible:ring-amber-300 forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        success:
          "border-emerald-300 bg-emerald-100 text-emerald-900 focus-visible:ring-emerald-800 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-100 dark:focus-visible:ring-emerald-300 forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
        neutral:
          "border-slate-300 bg-slate-100 text-slate-900 focus-visible:ring-slate-700 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:focus-visible:ring-slate-300 forced-colors:border-[CanvasText] forced-colors:text-[CanvasText]",
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
