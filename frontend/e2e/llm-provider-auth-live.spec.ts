import { expect, test } from "@playwright/test"

import { fulfillMockJson } from "./support/mock-backend"

test("local owner creates, rotates, tests, reloads, and deletes an LLM provider without a Settings login", async ({ page }) => {
  const providerSecret = "TEST_PROVIDER_SECRET_MUST_NOT_LEAK"
  const rotatedSecret = "TEST_ROTATED_PROVIDER_SECRET_MUST_NOT_LEAK"
  const providerName = `Browser local-owner provider ${Date.now()}`
  const updatedName = `${providerName} updated`
  let provider: Record<string, unknown> | null = null
  let persistedSecret: string | null = null
  page.on("dialog", async (dialog) => dialog.accept())
  await page.route("**/api/backend/llm-providers**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    if (request.method() === "GET" && path === "/llm-providers") {
      await fulfillMockJson(route, provider ? [provider] : [])
      return
    }
    if (request.method() === "POST" && path === "/llm-providers") {
      const input = request.postDataJSON() as Record<string, unknown>
      persistedSecret = String(input.api_key)
      provider = providerFixture(input)
      await fulfillMockJson(route, provider, 201)
      return
    }
    if (request.method() === "POST" && provider && path === `/llm-providers/${provider.id}/rotate-secret`) {
      const input = request.postDataJSON() as Record<string, unknown>
      persistedSecret = String(input.secret)
      provider = { ...provider, enabled: false, health_status: "unchecked" }
      await fulfillMockJson(route, provider)
      return
    }
    if (request.method() === "POST" && provider && path === `/llm-providers/${provider.id}/test`) {
      expect(persistedSecret).toBe(rotatedSecret)
      provider = {
        ...provider,
        health_status: "healthy",
        generation_capability: "ready",
        research_capability: "ready",
        generation_ready: true,
        research_ready: true,
        last_checked_at: "2026-07-31T12:02:00Z",
      }
      await fulfillMockJson(route, provider)
      return
    }
    if (request.method() === "PATCH" && provider && path === `/llm-providers/${provider.id}`) {
      const input = request.postDataJSON() as Record<string, unknown>
      provider = { ...provider, ...input, updated_at: "2026-07-31T12:01:00Z" }
      await fulfillMockJson(route, provider)
      return
    }
    if (request.method() === "GET" && provider && path === `/llm-providers/${provider.id}/dependencies`) {
      await fulfillMockJson(route, {
        active_jobs: 0,
        automations: 0,
        blocked: false,
        generation_runs: 0,
        research_runs: 0,
      })
      return
    }
    if (request.method() === "DELETE" && provider && path === `/llm-providers/${provider.id}`) {
      provider = null
      await route.fulfill({ status: 204 })
      return
    }
    await route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({ detail: `Unhandled mock request: ${request.method()} ${path}` }),
    })
  })

  await page.goto("/settings?section=llm-providers")
  await expect(page.getByRole("button", { name: /operator sign in/i })).toHaveCount(0)
  await expect(page.getByLabel(/operator secret/i)).toHaveCount(0)

  await page.getByRole("button", { name: "Add provider" }).click()
  const providerForm = page.getByRole("dialog", { name: "Add LLM provider" })
  await providerForm.getByLabel(/Connection name/).fill(providerName)
  await providerForm.getByLabel(/Model name/).fill("test/browser-local-owner")
  await providerForm.getByLabel(/Base URL/).fill("https://openrouter.ai/api/v1")
  await providerForm.getByLabel(/API key/).fill(providerSecret)
  await providerForm.getByRole("button", { name: "Add provider" }).click()
  await expect(providerForm).not.toBeVisible()

  let card = page.getByTestId("llm-provider-card").filter({ hasText: providerName })
  await expect(card).toBeVisible()
  await expect(card.locator('[data-provider-brand="openrouter"]')).toBeVisible()
  await card.getByRole("button", { name: "Edit" }).click()
  const editForm = page.getByRole("dialog", { name: `Edit ${providerName}` })
  await editForm.getByLabel(/Connection name/).fill(updatedName)
  await editForm.getByRole("button", { name: "Save provider" }).click()
  await expect(editForm).not.toBeVisible()

  card = page.getByTestId("llm-provider-card").filter({ hasText: updatedName })
  await expect(card).toBeVisible()
  await card.getByRole("button", { name: /More actions for/ }).click()
  await page.getByRole("menuitem", { name: "Rotate key" }).click()
  const rotationForm = page.getByRole("dialog", { name: `Rotate key for ${updatedName}` })
  await rotationForm.getByLabel(/New API key/).fill(rotatedSecret)
  await rotationForm.getByRole("button", { name: "Rotate secret" }).click()
  await expect(rotationForm).not.toBeVisible()
  await card.getByRole("button", { name: "Test" }).click()
  await expect(page.getByText("Connection tested", { exact: true })).toBeVisible()

  await page.reload()
  card = page.getByTestId("llm-provider-card").filter({ hasText: updatedName })
  await expect(card.getByText("Configured", { exact: true })).toBeVisible()
  await expect(card.getByText("healthy", { exact: true })).toBeVisible()

  await card.getByRole("button", { name: /More actions for/ }).click()
  const deletion = page.waitForResponse((response) =>
    response.request().method() === "DELETE"
      && response.url().includes("/api/backend/llm-providers/")
  )
  await page.getByRole("menuitem", { name: "Delete provider" }).click()
  const response = await deletion
  const headers = await response.request().allHeaders()
  const applicationOrigin = new URL(page.url()).origin

  expect(response.status()).toBe(204)
  expect({
    authorizationPresent: Boolean(headers.authorization),
    operatorCookiePresent: headers.cookie?.includes("newscraft_operator_session") ?? false,
    origin: headers.origin,
  }).toEqual({
    authorizationPresent: false,
    operatorCookiePresent: false,
    origin: applicationOrigin,
  })
  await expect(page.getByText("Provider deleted", { exact: true })).toBeVisible()
  await expect(card).not.toBeVisible()
  expect(await page.locator("body").innerText()).not.toContain(providerSecret)
  expect(await page.locator("body").innerText()).not.toContain(rotatedSecret)
  expect(await page.evaluate(() => [
    ...Object.values(localStorage),
    ...Object.values(sessionStorage),
  ])).toEqual(expect.not.arrayContaining([providerSecret, rotatedSecret]))
})

function providerFixture(input: Record<string, unknown>) {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    name: input.name,
    protocol: "openai_compatible",
    base_url: input.base_url,
    default_model: input.default_model,
    enabled: false,
    configured: true,
    settings: {
      timeout_seconds: 60,
      max_input_tokens: 60_000,
      max_output_tokens: 12_000,
      pricing: { input_usd_per_million: "0", output_usd_per_million: "0" },
      attribution_headers: { http_referer: null, app_title: "NewsCraft" },
    },
    health_status: "unchecked",
    generation_capability: "unknown",
    research_capability: "unknown",
    generation_ready: false,
    research_ready: false,
    failure_code: null,
    last_checked_at: null,
    ownership: "operator_managed",
    created_at: "2026-07-31T12:00:00Z",
    updated_at: "2026-07-31T12:00:00Z",
  }
}
