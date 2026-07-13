"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { getContentPackRequests } from "@/lib/editorial-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export default function DraftsPage() {
  const requests = useQuery({ queryKey: queryKeys.contentPackRequests, queryFn: getContentPackRequests })
  if (requests.isPending) return <main role="status" className="p-6">Loading durable draft requests…</main>
  if (requests.isError) return <main role="alert" className="p-6 text-red-700">{getApiErrorMessage(requests.error, "Draft requests could not be loaded")}</main>
  return <main className="space-y-4 p-4 md:p-6"><header><h1 className="text-2xl font-semibold">Drafts</h1><p className="text-muted-foreground">Durable generation requests and completed packs.</p></header>{requests.data?.length ? <ul className="grid gap-3">{requests.data.map((request) => <li key={request.id} className="rounded-lg border p-4"><div className="font-medium">{request.pack ? "Telegram content pack" : "Telegram generation request"}</div><div className="text-sm text-muted-foreground">{request.status.replaceAll("_", " ")} · updated {new Date(request.updatedAt).toLocaleString()}</div>{request.jobId ? <div className="text-xs text-muted-foreground">Job {request.jobId}</div> : null}{request.lastFailure ? <div role="alert" className="text-sm text-red-700">Last failure: {request.lastFailure}</div> : null}{request.pack ? <Link href={`/drafts/${request.pack.id}`} className="mt-2 inline-flex text-primary underline">Open editorial studio</Link> : <div role="status" className="mt-2 text-sm">{["failed", "needs_review"].includes(request.status) ? "Review required before a pack can be created." : "Generation has not created a pack yet."}</div>}</li>)}</ul> : <p>No durable generation requests yet. Generate a Telegram draft from the Inbox.</p>}</main>
}
