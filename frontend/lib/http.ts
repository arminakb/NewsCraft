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
      if (Array.isArray(parsed.detail)) {
        const messages = parsed.detail
          .map((item) => formatValidationError(item))
          .filter((message): message is string => Boolean(message))
        if (messages.length) return messages.join(" ")
      }
      if (parsed.detail && typeof parsed.detail === "object") {
        const detail = parsed.detail as { code?: unknown; message?: unknown; node_type?: unknown; field_path?: unknown }
        if (typeof detail.message === "string" && detail.message.trim()) return detail.message
        if (typeof detail.node_type === "string" && typeof detail.field_path === "string") {
          return `${detail.node_type}: ${detail.field_path}`
        }
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

function formatValidationError(value: unknown): string | null {
  if (!value || typeof value !== "object") return null
  const detail = value as {
    loc?: unknown
    msg?: unknown
    type?: unknown
    input?: unknown
    ctx?: Record<string, unknown>
  }
  const location = Array.isArray(detail.loc)
    ? detail.loc.filter((part): part is string | number => typeof part === "string" || typeof part === "number")
    : []
  const fieldPath = location.filter((part) => part !== "body").join(".") || "body"
  const type = typeof detail.type === "string" ? detail.type : ""
  const message = typeof detail.msg === "string" ? detail.msg.replace(/^Value error,\s*/i, "") : ""
  const label = fieldPath === "name" ? "Collection name" : fieldPath

  if (type === "missing") return `${label} is required.`
  if (type === "string_type") return withValidationContext(`${label} must be a string.`, fieldPath, "string", detail.input)
  if (type === "model_attributes_type") {
    return withValidationContext("Request body must be a JSON object.", fieldPath, "object", detail.input)
  }
  if (type === "extra_forbidden") {
    return withValidationContext(`${label} is not accepted.`, fieldPath, "no extra fields", detail.input)
  }
  if (message) return withValidationContext(capitalize(message), fieldPath, expectedType(type, detail.ctx), detail.input)
  return withValidationContext(`${label} is invalid.`, fieldPath, expectedType(type, detail.ctx), detail.input)
}

function withValidationContext(message: string, fieldPath: string, expected: string, input: unknown): string {
  if (process.env.NODE_ENV === "production") return message
  return `${message} (field_path=${fieldPath}; expected=${expected}; received=${describeType(input)})`
}

function expectedType(type: string, context: Record<string, unknown> | undefined): string {
  if (type === "string_too_long") return `string length <= ${String(context?.max_length ?? "limit")}`
  if (type === "uuid_parsing") return "UUID"
  if (type === "int_parsing") return "integer"
  if (type === "bool_parsing") return "boolean"
  if (type.endsWith("_type")) return type.slice(0, -5)
  return "valid value"
}

function describeType(input: unknown): string {
  if (input === undefined) return "missing"
  if (input === null) return "null"
  if (Array.isArray(input)) return "array"
  return typeof input
}

function capitalize(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value
}
