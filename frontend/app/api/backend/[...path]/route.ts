import { NextRequest, NextResponse } from "next/server"

const DEFAULT_BACKEND_BASE_URL = "http://localhost:8000"

// Connection-scoped headers (RFC 9110 §7.6.1) must never survive a proxy hop in
// either direction.
const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
] as const

// Framing metadata that stops being truthful once this handler re-frames the
// body: the request body is buffered here (so undici re-derives content-length)
// and the response body has already been decoded by undici.
const REQUEST_FRAMING_HEADERS = ["content-length"] as const
const RESPONSE_FRAMING_HEADERS = ["content-encoding", "content-length"] as const

// Client-supplied principal metadata is never trusted; the backend derives it.
const CLIENT_CONTROLLED_HEADERS = [
  "host",
  "x-newscraft-principal-type",
  "x-newscraft-scopes",
] as const

const CONNECTIVITY_ERROR_CODES = new Set([
  "EAI_AGAIN",
  "ECONNREFUSED",
  "ECONNRESET",
  "EHOSTUNREACH",
  "ENETUNREACH",
  "ENOTFOUND",
  "EPIPE",
  "ETIMEDOUT",
  "UND_ERR_CONNECT_TIMEOUT",
  "UND_ERR_SOCKET",
])

type RouteContext = {
  params: Promise<{ path?: string[] }>
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context)
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context)
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context)
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context)
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context)
}

async function proxyBackendRequest(request: NextRequest, context: RouteContext) {
  const { path = [] } = await context.params
  const targetUrl = new URL(`/${path.join("/")}${request.nextUrl.search}`, backendBaseUrl())

  let response: Response
  try {
    response = await fetch(targetUrl.toString(), {
      method: request.method,
      headers: requestHeaders(request),
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      redirect: "manual",
    })
  } catch (error) {
    return proxyFailureResponse(request.method, targetUrl.pathname, error)
  }

  return new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders(response.headers),
  })
}

function backendBaseUrl() {
  // NEXT_PUBLIC_API_BASE_URL is the browser-facing base and is inlined into the
  // client bundle; it must never select this proxy's upstream, otherwise
  // pointing the browser at the backend silently disables header sanitisation.
  return process.env.API_INTERNAL_BASE_URL ?? DEFAULT_BACKEND_BASE_URL
}

function requestHeaders(request: NextRequest) {
  const headers = new Headers(request.headers)
  deleteHeaders(headers, HOP_BY_HOP_HEADERS)
  deleteHeaders(headers, REQUEST_FRAMING_HEADERS)
  deleteHeaders(headers, CLIENT_CONTROLLED_HEADERS)
  return headers
}

function responseHeaders(source: Headers) {
  const headers = new Headers(source)
  deleteHeaders(headers, HOP_BY_HOP_HEADERS)
  deleteHeaders(headers, RESPONSE_FRAMING_HEADERS)
  return headers
}

function deleteHeaders(headers: Headers, names: readonly string[]) {
  for (const name of names) {
    headers.delete(name)
  }
}

function proxyFailureResponse(method: string, path: string, error: unknown) {
  const label = `[backend-proxy] ${method} ${path} failed`
  if (isAbortError(error)) {
    console.error(label, "client aborted the request")
    return new NextResponse(null, { status: 499, headers: { "cache-control": "no-store" } })
  }

  console.error(label, error)
  if (isConnectivityError(error)) {
    return proxyErrorJson(503, {
      code: "backend_unavailable",
      message: "NewsCraft API is unavailable. Start the backend service and retry.",
    })
  }

  return proxyErrorJson(502, {
    code: "proxy_error",
    message: `The NewsCraft proxy could not complete this request (${errorName(error)}).`,
  })
}

function proxyErrorJson(status: number, detail: { code: string; message: string }) {
  return NextResponse.json({ detail }, { status, headers: { "cache-control": "no-store" } })
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === "AbortError"
}

function isConnectivityError(error: unknown) {
  return CONNECTIVITY_ERROR_CODES.has(errorCauseCode(error) ?? "")
}

function errorCauseCode(error: unknown): string | undefined {
  if (!(error instanceof Error)) {
    return undefined
  }
  const cause: unknown = error.cause
  if (typeof cause !== "object" || cause === null) {
    return undefined
  }
  const code: unknown = (cause as { code?: unknown }).code
  return typeof code === "string" ? code : undefined
}

function errorName(error: unknown) {
  return error instanceof Error ? error.name : "UnknownError"
}
