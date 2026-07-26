"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, CircleAlert, FilePlus2, MoreHorizontal, X } from "lucide-react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useEffect, useState, type ReactNode } from "react"

import { addTextStory, changeStoryState, getInboxStories, type InboxStory, type InboxView } from "./api"

import { useNotices } from "@/components/providers/notice-provider"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { getApiErrorMessage } from "@/lib/http"
import { cn } from "@/lib/utils"

const VIEWS: Array<{
  value: InboxView
  label: string
  description: string
}> = [
  {
    value: "needs-decision",
    label: "Needs decision",
    description: "New stories awaiting shortlist or rejection.",
  },
  {
    value: "ready-to-generate",
    label: "Ready to generate",
    description: "Shortlisted stories with complete research.",
  },
  {
    value: "research-incomplete",
    label: "Research incomplete",
    description: "Shortlisted stories still missing evidence.",
  },
]

export function InboxPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const view = parseView(searchParams.get("view"))
  const [addOpen, setAddOpen] = useState(searchParams.get("add") === "story")
  const storiesQuery = useQuery({
    queryKey: ["stories", "inbox", view],
    queryFn: () => getInboxStories(view),
  })
  const stateMutation = useMutation({
    mutationFn: ({ storyId, state }: { storyId: string; state: "inbox" | "shortlisted" | "rejected" }) =>
      changeStoryState(storyId, state),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["stories", "inbox"] })
      pushNotice({ tone: "success", title: "Story updated", message: "The editorial queue is current." })
    },
    onError: (error) =>
      pushNotice({ tone: "error", title: "Story update failed", message: getApiErrorMessage(error) }),
  })

  useEffect(() => setAddOpen(searchParams.get("add") === "story"), [searchParams])

  const closeAddStory = () => {
    setAddOpen(false)
    const params = new URLSearchParams(searchParams.toString())
    params.delete("add")
    router.replace(params.size ? `/inbox?${params.toString()}` : "/inbox")
  }

  return (
    <section className="mx-auto min-w-0 max-w-[1400px] space-y-5 p-4 md:p-6" aria-labelledby="inbox-heading">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b pb-4">
        <div>
          <h1 id="inbox-heading" className="text-2xl font-semibold tracking-tight">Inbox</h1>
          <p className="mt-1 text-sm text-muted-foreground">Make the next editorial decision, then move on.</p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <FilePlus2 aria-hidden="true" />
          Add story
        </Button>
      </header>

      <nav aria-label="Inbox views" className="flex flex-wrap gap-2">
        {VIEWS.map((item) => (
          <Link
            aria-current={item.value === view ? "page" : undefined}
            className={buttonVariants({ variant: item.value === view ? "secondary" : "outline" })}
            href={item.value === "needs-decision" ? "/inbox" : `/inbox?view=${item.value}`}
            key={item.value}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <p className="text-sm text-muted-foreground">{VIEWS.find((item) => item.value === view)?.description}</p>

      {storiesQuery.isPending ? (
        <div aria-label="Loading inbox" className="space-y-3" role="status">
          {Array.from({ length: 4 }, (_, index) => (
            <div aria-hidden="true" className="h-24 animate-pulse rounded-xl bg-muted" key={index} />
          ))}
        </div>
      ) : null}

      {storiesQuery.isError ? (
        <Card size="sm">
          <CardContent className="space-y-3 p-5">
            <p className="text-red-700" dir="auto" role="alert">
              {getApiErrorMessage(storiesQuery.error, "Inbox could not be loaded")}
            </p>
            <Button onClick={() => void storiesQuery.refetch()} variant="outline">Retry</Button>
          </CardContent>
        </Card>
      ) : null}

      {storiesQuery.isSuccess && storiesQuery.data.length === 0 ? (
        <Card size="sm">
          <CardContent className="p-10 text-center">
            <CheckCircle2 className="mx-auto size-8 text-teal-700" aria-hidden="true" />
            <h2 className="mt-3 font-semibold">This view is clear</h2>
            <p className="mt-1 text-sm text-muted-foreground">No stories currently match this decision state.</p>
          </CardContent>
        </Card>
      ) : null}

      {storiesQuery.data?.length ? (
        <div className="divide-y rounded-xl border bg-card" aria-label="Inbox stories">
          {storiesQuery.data.map((story) => (
            <StoryRow
              key={story.id}
              story={story}
              view={view}
              pending={stateMutation.isPending && stateMutation.variables?.storyId === story.id}
              onState={(state) => stateMutation.mutate({ storyId: story.id, state })}
            />
          ))}
        </div>
      ) : null}

      {addOpen ? <AddStoryDialog onClose={closeAddStory} /> : null}
    </section>
  )
}

function StoryRow({
  story,
  view,
  pending,
  onState,
}: {
  story: InboxStory
  view: InboxView
  pending: boolean
  onState: (state: "inbox" | "shortlisted" | "rejected") => void
}) {
  const incomplete = !story.completeness.complete
  return (
    <article className="grid gap-3 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
      <div className="min-w-0">
        <h2 className="truncate font-semibold" dir="auto">{story.title}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant={incomplete ? "outline" : "secondary"}>
            {incomplete ? <CircleAlert aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
            {incomplete ? `Research ${story.completeness.score}%` : "Research complete"}
          </Badge>
          <span>{story.evidenceCount} {story.evidenceCount === 1 ? "source" : "sources"}</span>
          <span dir="ltr">{story.primaryLanguage.toUpperCase()}</span>
        </div>
      </div>
      <div className="flex items-center justify-end gap-2">
        {view === "needs-decision" ? (
          <Button disabled={pending} onClick={() => onState("shortlisted")}>Shortlist</Button>
        ) : view === "ready-to-generate" ? (
          <Link className={buttonVariants()} href="/jobs">Open job queue</Link>
        ) : (
          <Button disabled={pending} onClick={() => onState("inbox")}>Return to inbox</Button>
        )}
        <details className="group relative">
          <summary
            aria-label={`More actions for ${story.title}`}
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "cursor-pointer list-none")}
          >
            <MoreHorizontal aria-hidden="true" />
          </summary>
          <div className="absolute right-0 z-20 mt-1 grid min-w-40 gap-1 rounded-lg border bg-background p-1 shadow-lg">
            {view !== "needs-decision" ? (
              <Button disabled={pending} onClick={() => onState("inbox")} variant="ghost">Move to inbox</Button>
            ) : null}
            <Button disabled={pending} onClick={() => onState("rejected")} variant="ghost">Reject</Button>
          </div>
        </details>
      </div>
    </article>
  )
}

function AddStoryDialog({ onClose }: { onClose: () => void }) {
  const { pushNotice } = useNotices()
  const [form, setForm] = useState({ title: "", sourceLabel: "", sourceUrl: "", text: "" })
  const mutation = useMutation({
    mutationFn: () =>
      addTextStory({
        title: form.title.trim(),
        sourceLabel: form.sourceLabel.trim(),
        sourceUrl: form.sourceUrl.trim() || null,
        text: form.text.trim(),
      }),
    onSuccess: () => {
      pushNotice({ tone: "success", title: "Story queued", message: "The source text is being added to Inbox." })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4" role="presentation">
      <div
        aria-labelledby="add-story-heading"
        aria-modal="true"
        className="max-h-[calc(100dvh-2rem)] w-full max-w-2xl overflow-y-auto rounded-xl border bg-background p-5 shadow-xl"
        role="dialog"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold" id="add-story-heading">Add story</h2>
            <p className="mt-1 text-sm text-muted-foreground">Paste source text now; collection continues in the background.</p>
          </div>
          <Button aria-label="Close Add story" onClick={onClose} size="icon" variant="ghost"><X aria-hidden="true" /></Button>
        </div>
        <form
          className="mt-5 grid gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <Field label="Title">
            <input
              className="min-h-11 rounded-lg border bg-background px-3"
              maxLength={300}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              required
              value={form.title}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Source label">
              <input
                className="min-h-11 rounded-lg border bg-background px-3"
                maxLength={160}
                onChange={(event) => setForm({ ...form, sourceLabel: event.target.value })}
                required
                value={form.sourceLabel}
              />
            </Field>
            <Field label="Source URL (optional)">
              <input
                className="min-h-11 rounded-lg border bg-background px-3"
                onChange={(event) => setForm({ ...form, sourceUrl: event.target.value })}
                type="url"
                value={form.sourceUrl}
              />
            </Field>
          </div>
          <Field label="Source text">
            <textarea
              className="min-h-44 resize-y rounded-lg border bg-background p-3"
              maxLength={200_000}
              minLength={20}
              onChange={(event) => setForm({ ...form, text: event.target.value })}
              required
              value={form.text}
            />
          </Field>
          {mutation.isError ? (
            <p className="text-sm text-red-700" dir="auto" role="alert">
              {getApiErrorMessage(mutation.error, "Story could not be queued")}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button disabled={mutation.isPending} onClick={onClose} type="button" variant="outline">Cancel</Button>
            <Button disabled={mutation.isPending} type="submit">
              {mutation.isPending ? "Adding…" : "Add to Inbox"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium">
      {label}
      {children}
    </label>
  )
}

function parseView(value: string | null): InboxView {
  return VIEWS.some((item) => item.value === value) ? value as InboxView : "needs-decision"
}
