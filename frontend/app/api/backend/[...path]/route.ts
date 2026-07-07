import { NextRequest, NextResponse } from "next/server"

const DEFAULT_BACKEND_BASE_URL = "http://localhost:8000"
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
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
  const headers = new Headers(request.headers)
  headers.delete("host")

  const response = await fetch(targetUrl.toString(), {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
    redirect: "manual",
  })

  return new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders(response.headers),
  })
}

function backendBaseUrl() {
  return process.env.API_INTERNAL_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BACKEND_BASE_URL
}

function responseHeaders(source: Headers) {
  const headers = new Headers(source)
  for (const name of HOP_BY_HOP_HEADERS) {
    headers.delete(name)
  }
  return headers
}
