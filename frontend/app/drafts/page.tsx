"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { TelegramDraftList } from "@/features/drafts/telegram-draft-list"
import { getContentPackRequests } from "@/features/editorial/api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export default function DraftsPage() {
  const requests = useQuery({ queryKey: queryKeys.contentPackRequests, queryFn: getContentPackRequests })
  return <section className="space-y-6 p-4 md:p-6" aria-labelledby="drafts-heading">
    <header><h1 id="drafts-heading" className="text-2xl font-semibold">Drafts</h1><p className="text-muted-foreground">Durable generation requests and completed packs.</p></header>
    <section aria-labelledby="durable-draft-requests-heading" className="space-y-4">
      <h2 id="durable-draft-requests-heading" className="text-xl font-semibold">Durable generation requests</h2>
      {requests.isPending ? <div role="status">Loading durable draft requests…</div> : null}
      {requests.isError ? <div role="alert" className="text-red-700">{getApiErrorMessage(requests.error, "Draft requests could not be loaded")}</div> : null}
      {requests.isSuccess && requests.data.length ? <ul className="grid gap-3">{requests.data.map((request) => <li key={request.id} className="rounded-lg border p-4"><div className="font-medium">{request.pack ? "Telegram content pack" : "Telegram generation request"}</div><div className="text-sm text-muted-foreground">{request.status.replaceAll("_", " ")} · updated {new Date(request.updatedAt).toLocaleString()}</div>{request.jobId ? <div className="text-xs text-muted-foreground">Job {request.jobId}</div> : null}{request.lastFailure ? <div role="alert" className="text-sm text-red-700">Last failure: {request.lastFailure}</div> : null}{request.pack ? <Link href={`/drafts/${request.pack.id}`} className="mt-2 inline-flex text-primary underline">Open editorial studio</Link> : <div role="status" className="mt-2 text-sm">{["failed", "needs_review"].includes(request.status) ? "Review required before a pack can be created." : "Generation has not created a pack yet."}</div>}</li>)}</ul> : null}
      {requests.isSuccess && !requests.data.length ? <p>No durable generation requests yet.</p> : null}
    </section>
    <TelegramDraftList />
  </section>
}
