"use client"

import {
  ArrowLeft,
  CirclePause,
  FlaskConical,
  History,
  ListTree,
  LoaderCircle,
  MoreHorizontal,
  Play,
  Redo2,
  Save,
  ShieldCheck,
  Undo2,
} from "lucide-react"
import Link from "next/link"
import type { RefObject } from "react"

import { Button, buttonVariants } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/menu"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"

type WorkflowToolbarProps = {
  title: string
  versionNumber: number
  dirty: boolean
  lifecycle: { label: string; tone: StatusTone }
  readiness: { label: string; tone: StatusTone; issueCount: number }
  attentionTriggerRef?: RefObject<HTMLButtonElement | null>
  pending: boolean
  savePending: boolean
  validationPending: boolean
  lifecyclePending: boolean
  undoDisabled: boolean
  redoDisabled: boolean
  saveDisabled: boolean
  lifecycleDisabled: boolean
  lifecycleAction: "Activate" | "Pause" | "Resume"
  onUndo: () => void
  onRedo: () => void
  onOpenOrderedEditor: () => void
  onOpenHistory: () => void
  onOpenTestStudio: () => void
  onOpenAttention?: () => void
  onSave: () => void
  onValidate: () => void
  onLifecycleAction: () => void
}

export function WorkflowToolbar({
  title,
  versionNumber,
  dirty,
  lifecycle,
  readiness,
  attentionTriggerRef,
  pending,
  savePending,
  validationPending,
  lifecyclePending,
  undoDisabled,
  redoDisabled,
  saveDisabled,
  lifecycleDisabled,
  lifecycleAction,
  onUndo,
  onRedo,
  onOpenOrderedEditor,
  onOpenHistory,
  onOpenTestStudio,
  onOpenAttention,
  onSave,
  onValidate,
  onLifecycleAction,
}: WorkflowToolbarProps) {
  const hasAttention = readiness.issueCount > 0 && Boolean(onOpenAttention)

  return (
    <header
      aria-label="Workflow toolbar"
      className="grid min-h-14 shrink-0 grid-cols-[auto_minmax(7rem,1fr)_auto] items-center gap-2 border-b border-border/60 bg-background px-2.5 shadow-xs min-[768px]:px-3"
    >
      <Link
        aria-label="Back to workflow library"
        className={buttonVariants({ variant: "ghost", size: "icon" })}
        href="/automations"
      >
        <ArrowLeft aria-hidden="true" />
      </Link>
      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold leading-5" id="automations-heading" title={title}>{title}</h1>
        <p className="truncate text-xs text-muted-foreground">
          Version {versionNumber} · {dirty ? "Unsaved changes" : "Draft saved"}
        </p>
      </div>
      <div className="flex min-w-0 items-center justify-end gap-1 overflow-x-auto py-1" data-workflow-toolbar-actions>
        <StatusBadge className="hidden min-[1100px]:inline-flex" tone={lifecycle.tone}>{lifecycle.label}</StatusBadge>
        {hasAttention ? (
          <Button
            aria-label={`${readiness.label}, ${readiness.issueCount} ${readiness.issueCount === 1 ? "issue" : "issues"}`}
            className="min-h-11 gap-1.5 px-1.5 min-[900px]:min-h-8"
            onClick={onOpenAttention}
            ref={attentionTriggerRef}
            size="sm"
            title="Review workflow validation issues"
            type="button"
            variant="ghost"
          >
            <StatusBadge className="pointer-events-none" tone={readiness.tone}>{readiness.label}</StatusBadge>
            <span aria-hidden="true" className="rounded-md border border-border/70 bg-muted px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">{readiness.issueCount}</span>
          </Button>
        ) : <StatusBadge className="hidden min-[1200px]:inline-flex" tone={readiness.tone}>{readiness.label}</StatusBadge>}
        <Button aria-label="Undo workflow change" disabled={undoDisabled || pending} onClick={onUndo} size="icon" variant="ghost"><Undo2 aria-hidden="true" /></Button>
        <Button aria-label="Redo workflow change" disabled={redoDisabled || pending} onClick={onRedo} size="icon" variant="ghost"><Redo2 aria-hidden="true" /></Button>
        <Button aria-label="Open ordered editor" disabled={pending} onClick={onOpenOrderedEditor} size="icon" variant="ghost"><ListTree aria-hidden="true" /></Button>
        <Button aria-label="Test" className="px-2 min-[1440px]:w-auto min-[1440px]:px-3" disabled={pending || dirty} onClick={onOpenTestStudio} size="icon" variant="outline">
          <FlaskConical aria-hidden="true" />
          <span className="hidden min-[1440px]:inline">Test</span>
        </Button>
        <Button aria-label="Save draft" className="px-2 min-[1440px]:w-auto min-[1440px]:px-3" disabled={saveDisabled} onClick={onSave} size="icon" variant="outline">
          {savePending ? <LoaderCircle className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Save aria-hidden="true" />}
          <span className="hidden min-[1440px]:inline">{savePending ? "Saving…" : "Save draft"}</span>
        </Button>
        <Button aria-label={lifecycleAction} className="px-2 min-[1440px]:w-auto min-[1440px]:px-3" disabled={lifecycleDisabled} onClick={onLifecycleAction} size="icon">
          {lifecyclePending ? <LoaderCircle className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : lifecycleAction === "Pause" ? <CirclePause aria-hidden="true" /> : lifecycleAction === "Activate" ? <Play aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />}
          <span className="hidden min-[1440px]:inline">{lifecycleAction}</span>
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger aria-label="More workflow actions" className={buttonVariants({ variant: "ghost", size: "icon" })} disabled={pending}>
            <MoreHorizontal aria-hidden="true" />
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem onClick={onOpenHistory}><History aria-hidden="true" className="size-4" />Version history</DropdownMenuItem>
            <DropdownMenuItem disabled={dirty || validationPending} onClick={onValidate}>
              {validationPending ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <ShieldCheck aria-hidden="true" className="size-4" />}
              {validationPending ? "Validating…" : "Validate saved version"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
