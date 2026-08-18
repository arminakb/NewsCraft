"use client"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"

type DirtyNavigationDialogProps = {
  open: boolean
  description: string
  returnFocus: HTMLElement | null
  onCancel: () => void
  onDiscard: () => void
}

export function DirtyNavigationDialog({
  open,
  description,
  returnFocus,
  onCancel,
  onDiscard,
}: DirtyNavigationDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onCancel()
      }}
    >
      <DialogContent
        className="max-w-md"
        overlayClassName="z-[100]"
        viewportClassName="z-[110]"
        data-testid="unsaved-changes-dialog"
        finalFocus={() => returnFocus}
      >
        <DialogHeader>
          <DialogTitle>Unsaved changes</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={onDiscard}>
            Discard changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
