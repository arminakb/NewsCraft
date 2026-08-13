import { ApiError, getApiErrorMessage } from "@/lib/http"

describe("API validation error mapping", () => {
  afterEach(() => vi.unstubAllEnvs())

  it("maps a missing collection name to a useful message", () => {
    const error = new ApiError(
      "Unprocessable Content",
      422,
      JSON.stringify({
        detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
      }),
    )

    expect(getApiErrorMessage(error)).toBe("Collection name is required.")
  })

  it("maps a type mismatch without exposing the submitted value", () => {
    const error = new ApiError(
      "Unprocessable Content",
      422,
      JSON.stringify({
        detail: [{
          loc: ["body", "description"],
          msg: "Input should be a valid string",
          type: "string_type",
          input: "secret description",
        }],
      }),
    )

    expect(getApiErrorMessage(error)).toContain("description must be a string.")
    expect(getApiErrorMessage(error)).toContain("field_path=description")
    expect(getApiErrorMessage(error)).not.toContain("secret description")
  })

  it("omits field-path context in production while preserving the safe message", () => {
    vi.stubEnv("NODE_ENV", "production")
    const error = new ApiError(
      "Unprocessable Content",
      422,
      JSON.stringify({
        detail: [{ loc: ["body", "description"], msg: "Input should be a valid string", type: "string_type", input: "secret" }],
      }),
    )

    expect(getApiErrorMessage(error)).toBe("description must be a string.")
  })

  it("maps a body-shape mismatch with safe development context", () => {
    const error = new ApiError(
      "Unprocessable Content",
      422,
      JSON.stringify({
        detail: [{
          loc: ["body"],
          msg: "Input should be a valid dictionary or object to extract fields from",
          type: "model_attributes_type",
          input: "{\"name\":\"AI Sources\"}",
        }],
      }),
    )

    expect(getApiErrorMessage(error)).toBe(
      "Request body must be a JSON object. (field_path=body; expected=object; received=string)",
    )
    expect(getApiErrorMessage(error)).not.toContain("AI Sources")
  })

  it("maps structured Source Collection conflicts", () => {
    const error = new ApiError(
      "Conflict",
      409,
      JSON.stringify({ detail: { code: "source_collection_conflict", message: "source collection name already exists" } }),
    )

    expect(getApiErrorMessage(error)).toBe("source collection name already exists")
  })
})
