import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Page, type Route } from "@playwright/test"

import { installMockBackend } from "./support/mock-backend"

const proxy = {
  id: "55555555-5555-4555-8555-555555555555",
  name: "Publishing proxy with a long operator-facing profile name",
  proxy_type: "socks5",
  host: "proxy-with-a-long-hostname.publishing.example",
  port: 1080,
  enabled: true,
  credentials_configured: true,
  reachability_status: "healthy",
  failure_code: null,
  last_checked_at: "2026-07-23T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

const initialDestination = {
  id: "66666666-6666-4666-8666-666666666666",
  name: "Main newsroom channel with a deliberately long destination name",
  target_ref: "@newscraft_editorial_updates_with_a_long_identifier",
  canonical_target: "@newscraft_editorial_updates_with_a_long_identifier",
  target_type: "username",
  enabled: true,
  health_status: "healthy",
  configured: true,
  proxy_profile_id: proxy.id,
  connection_route: proxy.name,
  proxy_health_status: "healthy",
  telegram_health_status: "healthy",
  bot_health_status: "authenticated",
  target_health_status: "resolved",
  administrator_status: "administrator",
  failure_code: null,
  verified_bot_id: 42,
  verified_bot_username: "newscraft_bot_with_a_long_username",
  verified_chat_id: -10042,
  verified_chat_title: "NewsCraft editorial updates with a long verified title",
  verified_chat_type: "channel",
  last_checked_at: "2026-07-23T08:00:00Z",
  last_rotated_at: null,
  created_at: "2026-07-23T07:00:00Z",
  updated_at: "2026-07-23T08:00:00Z",
}

type TelegramDestinationFixture = Omit<typeof initialDestination, "proxy_profile_id"> & {
  proxy_profile_id: string | null
}

test("Telegram Settings stays compact and preserves destination workflows", async ({ page }, testInfo) => {
  const unhandledRequests = await installMockBackend(page)
  const backend = await installTelegramSettingsBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/settings?section=telegram")

  const originalCard = page.getByTestId("telegram-destination-card").filter({
    hasText: initialDestination.name,
  })
  await expect(originalCard).toBeVisible()
  await expect(originalCard.getByText(initialDestination.canonical_target)).toHaveAttribute(
    "title",
    initialDestination.canonical_target,
  )
  await expect(originalCard.getByText(`Proxy: ${proxy.name}`)).toBeVisible()
  await expect(originalCard.getByText("Telegram API", { exact: true })).toHaveCount(1)
  await expect(originalCard.getByText("Administrator", { exact: true })).toHaveCount(1)
  await expect(originalCard.getByRole("group", {
    name: `Primary actions for ${initialDestination.name}`,
  }).getByRole("button")).toHaveCount(3)
  expect((await originalCard.boundingBox())?.height).toBeLessThan(280)

  await originalCard.getByRole("button", {
    name: `More actions for ${initialDestination.name}`,
  }).click()
  await expect(page.getByRole("menuitem", { name: "Rotate bot token" })).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "View dependencies" })).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "Delete destination" })).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByText("Proxy profiles (1)", { exact: true }).click()
  const proxyCard = page.getByTestId("telegram-proxy-card")
  await expect(proxyCard).toBeVisible()
  await expect(proxyCard.locator("p").filter({ hasText: `${proxy.host}:${proxy.port}` })).toHaveAttribute(
    "title",
    `${proxy.host}:${proxy.port}`,
  )
  await expect(proxyCard.getByRole("group", {
    name: `Primary actions for ${proxy.name}`,
  }).getByRole("button")).toHaveCount(3)
  await proxyCard.getByRole("button", { name: `More actions for ${proxy.name}` }).click()
  await expect(page.getByRole("menuitem", { name: "Manage credentials" })).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "Delete proxy" })).toBeVisible()
  await page.keyboard.press("Escape")

  const accessibility = await new AxeBuilder({ page })
    .include('[data-testid^="telegram-"]')
    .analyze()
  expect(accessibility.violations.filter(({ impact }) =>
    impact === "critical" || impact === "serious"
  )).toEqual([])
  await page.screenshot({ path: testInfo.outputPath("telegram-proxies-1440.png") })
  await page.getByText("Proxy profiles (1)", { exact: true }).click()

  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    if (!(await originalCard.isVisible())) {
      await page.getByRole("dialog", { name: "Settings" })
        .getByRole("button", { name: "Telegram", exact: true })
        .click()
    }
    await expect(originalCard).toBeVisible()
    const bounds = await originalCard.boundingBox()
    expect(bounds?.x).toBeGreaterThanOrEqual(0)
    expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(width)
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth <= document.documentElement.clientWidth
      && document.body.scrollWidth <= window.innerWidth
    )).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`telegram-settings-${width}.png`) })
  }

  const mobileActions = originalCard.getByRole("group", {
    name: `Primary actions for ${initialDestination.name}`,
  }).getByRole("button")
  for (const button of await mobileActions.all()) {
    expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(44)
  }
  expect((await originalCard.getByRole("button", {
    name: `More actions for ${initialDestination.name}`,
  }).boundingBox())?.height).toBeGreaterThanOrEqual(44)

  await page.getByRole("button", { name: "Add destination" }).click()
  const addDialog = page.getByRole("dialog", { name: "Add Telegram destination" })
  const addBounds = await addDialog.boundingBox()
  expect(addBounds?.x).toBeGreaterThanOrEqual(0)
  expect((addBounds?.x ?? 0) + (addBounds?.width ?? 0)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: testInfo.outputPath("telegram-add-destination-390.png") })
  await addDialog.getByLabel(/Destination name/).fill("Mobile alerts")
  await addDialog.getByLabel(/Channel or group identifier/).fill("@mobile_alerts")
  await addDialog.getByLabel(/Bot token/).fill("TEST_TELEGRAM_TOKEN_MUST_NOT_RENDER")
  await addDialog.getByLabel("Connection route").selectOption(proxy.id)
  await addDialog.getByRole("button", { name: "Add destination" }).click()

  const createdCard = page.getByTestId("telegram-destination-card").filter({ hasText: "Mobile alerts" })
  await expect(createdCard).toBeVisible()
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  expect(await page.locator("body").textContent()).not.toContain("TEST_TELEGRAM_TOKEN_MUST_NOT_RENDER")

  await createdCard.getByRole("button", { name: "Edit" }).click()
  const editDialog = page.getByRole("dialog", { name: "Edit Mobile alerts" })
  await editDialog.getByLabel(/Destination name/).fill("Mobile alerts updated")
  await editDialog.getByLabel("Connection route").selectOption("")
  await editDialog.getByRole("button", { name: "Save destination" }).click()

  const updatedCard = page.getByTestId("telegram-destination-card").filter({
    hasText: "Mobile alerts updated",
  })
  await expect(updatedCard.getByText("Direct", { exact: true })).toBeVisible()

  await updatedCard.getByRole("button", { name: "Edit" }).click()
  const assignDialog = page.getByRole("dialog", { name: "Edit Mobile alerts updated" })
  await assignDialog.getByLabel("Connection route").selectOption(proxy.id)
  await assignDialog.getByRole("button", { name: "Save destination" }).click()
  await expect(updatedCard.getByText(`Proxy: ${proxy.name}`)).toBeVisible()

  await updatedCard.getByRole("button", { name: "Check" }).click()
  await expect.poll(() => backend.rechecks).toBe(1)
  await updatedCard.getByRole("button", { name: "Disable" }).click()
  await expect(updatedCard.getByRole("button", { name: "Enable" })).toBeVisible()
  await updatedCard.getByRole("button", { name: "Enable" }).click()
  await expect(updatedCard.getByRole("button", { name: "Disable" })).toBeVisible()

  page.once("dialog", (dialog) => void dialog.accept())
  await updatedCard.getByRole("button", { name: "More actions for Mobile alerts updated" }).click()
  await page.getByRole("menuitem", { name: "Delete destination" }).click()
  await expect(updatedCard).toHaveCount(0)

  expect(backend.created).toBe(1)
  expect(backend.updated).toBe(2)
  expect(backend.deleted).toBe(1)
  expect(unhandledRequests).toEqual([])
})

async function installTelegramSettingsBackend(page: Page) {
  const state = {
    created: 0,
    deleted: 0,
    destinations: [{ ...initialDestination }] as TelegramDestinationFixture[],
    rechecks: 0,
    updated: 0,
  }

  await page.route("**/api/backend/telegram/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace("/api/backend", "")
    const method = request.method()

    if (method === "GET" && path === "/telegram/destinations") {
      await json(route, state.destinations)
      return
    }
    if (method === "GET" && path === "/telegram/proxies") {
      await json(route, [proxy])
      return
    }
    if (method === "POST" && path === "/telegram/destinations") {
      const body = request.postDataJSON() as Record<string, unknown>
      const destination = {
        ...initialDestination,
        id: "77777777-7777-4777-8777-777777777777",
        name: String(body.name),
        target_ref: String(body.target),
        canonical_target: String(body.target),
        proxy_profile_id: body.proxy_profile_id ? String(body.proxy_profile_id) : null,
        connection_route: body.proxy_profile_id ? proxy.name : "direct",
        proxy_health_status: body.proxy_profile_id ? "healthy" : "direct",
      }
      state.created += 1
      state.destinations.push(destination)
      await json(route, { destination, job: acceptedJob() }, 202)
      return
    }

    const match = path.match(/^\/telegram\/destinations\/([^/]+)(?:\/(.*))?$/)
    if (match) {
      const [, id, action] = match
      const index = state.destinations.findIndex((destination) => destination.id === id)
      const current = state.destinations[index]
      if (method === "PATCH" && current) {
        const body = request.postDataJSON() as Record<string, unknown>
        const profileId = body.proxy_profile_id === undefined
          ? current.proxy_profile_id
          : body.proxy_profile_id ? String(body.proxy_profile_id) : null
        const updated = {
          ...current,
          ...(body.name === undefined ? {} : { name: String(body.name) }),
          ...(body.target === undefined ? {} : {
            target_ref: String(body.target),
            canonical_target: String(body.target),
          }),
          proxy_profile_id: profileId,
          connection_route: profileId ? proxy.name : "direct",
          proxy_health_status: profileId ? "healthy" : "direct",
        }
        state.destinations[index] = updated
        state.updated += 1
        await json(route, { destination: updated, job: acceptedJob() })
        return
      }
      if (method === "GET" && action === "dependencies") {
        await json(route, {
          active_jobs: 0,
          automations: 0,
          blocked: false,
          publications: 0,
          publish_jobs: 0,
        })
        return
      }
      if (method === "POST" && action === "recheck" && current) {
        state.rechecks += 1
        await json(route, { destination: current, job: acceptedJob() }, 202)
        return
      }
      if (method === "POST" && (action === "disable" || action === "enable") && current) {
        state.destinations[index] = { ...current, enabled: action === "enable" }
        await json(route, state.destinations[index])
        return
      }
      if (method === "DELETE" && !action && current) {
        state.destinations.splice(index, 1)
        state.deleted += 1
        await route.fulfill({ status: 204 })
        return
      }
    }

    await route.fallback()
  })

  return state
}

function acceptedJob() {
  return {
    job_id: "88888888-8888-4888-8888-888888888888",
    status: "queued",
    deduplicated: false,
  }
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  })
}
