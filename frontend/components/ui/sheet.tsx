"use client"

import * as React from "react"

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

const Sheet = Dialog
const SheetTrigger = DialogTrigger
const SheetClose = DialogClose
const SheetHeader = DialogHeader
const SheetTitle = DialogTitle
const SheetDescription = DialogDescription
const SheetFooter = DialogFooter

function SheetContent({
  side = "right",
  className,
  ...props
}: React.ComponentProps<typeof DialogContent> & { side?: "right" | "bottom" }) {
  return (
    <DialogContent
      className={cn(
        "m-0 max-h-dvh rounded-none p-0",
        side === "right" ? "h-dvh max-w-md" : "max-h-[85dvh] max-w-none rounded-t-xl",
        className,
      )}
      viewportClassName={cn(
        "p-0",
        side === "right" ? "flex items-stretch justify-end" : "flex items-end justify-stretch",
      )}
      {...props}
    />
  )
}

export { Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle, SheetTrigger }
