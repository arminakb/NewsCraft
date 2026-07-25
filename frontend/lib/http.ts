export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend"

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) {
    throw new ApiError(response.statusText || "Request failed", response.status, await response.text())
  }
  return response.json() as Promise<T>
}

export async function apiRequestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) {
    throw new ApiError(response.statusText || "Request failed", response.status, await response.text())
  }
}

export function getApiErrorMessage(error: unknown, fallback = "Request failed") {
  if (error instanceof ApiError && error.body) {
    try {
      const parsed = JSON.parse(error.body) as {
        detail?: unknown
      }
      if (typeof parsed.detail === "string" && parsed.detail.trim()) return parsed.detail
      if (parsed.detail && typeof parsed.detail === "object") {
        const detail = parsed.detail as { code?: unknown; message?: unknown }
        if (typeof detail.message === "string" && detail.message.trim()) return detail.message
        if (typeof detail.code === "string" && detail.code.trim()) {
          return detail.code.replaceAll("_", " ")
        }
      }
    } catch {
      if (!error.body.trimStart().startsWith("<") && error.body.trim()) return error.body.trim()
    }
  }
  return error instanceof Error && error.message ? error.message : fallback
}
