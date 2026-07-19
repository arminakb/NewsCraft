import AxeBuilder from "@axe-core/playwright"
import { expect, test } from "@playwright/test"

import { installMockBackend, type MockStory } from "./support/mock-backend"
import type { components } from "../lib/api/generated"

const ROUTES = [
  { path: "/", name: "Today", readyText: "No workflow jobs yet" },
  { path: "/inbox", name: "Editorial Inbox", readyText: "No grouped stories match these filters." },
  { path: "/automations", name: "Telegram automations", readyText: "No Telegram automations yet" },
  { path: "/drafts", name: "Drafts", readyText: "No durable generation requests yet. Generate a Telegram draft from the Inbox." },
  { path: "/calendar", name: "Publication calendar", readyText: "No publication events in this calendar window." },
  { path: "/diagnostics", name: "Diagnostics", readyText: "System checks" },
] as const

const VIEWPORTS = [
  { label: "desktop", width: 1440, height: 1000 },
  { label: "mobile", width: 390, height: 844 },
] as const

const THEMES = ["light", "dark"] as const

const MOBILE_ACTION_STORY = {
  id: "story-mobile-actions",
  title: "Election timeline",
  status: "inbox",
  primary_language: "en",
  evidence_count: 2,
  latest_evidence_at: "2026-07-13T08:00:00Z",
  completeness: { complete: false, score: 40, reasons: ["More sources needed"] },
  evidence_set_hash: "a".repeat(64),
  created_at: "2026-07-13T07:00:00Z",
  updated_at: "2026-07-13T08:00:00Z",
} satisfies MockStory

const DIAGNOSTICS_STATUS_FIXTURE = {
  generated_at: "2026-07-13T08:00:00Z",
  global_paused: false,
  dry_run: true,
  components: Object.fromEntries(
    (["healthy", "degraded", "down", "unknown"] as const).map((status, index) => [
      `component-${status}`,
      {
        status,
        observed_at: index === 3 ? null : "2026-07-13T07:59:00Z",
        last_success_at: index === 0 ? "2026-07-13T07:58:00Z" : null,
        message: `${status} component state`,
        action_url: status === "healthy" ? null : "/diagnostics",
      },
    ]),
  ),
  queue_counts: {},
  attention: [
    {
      id: "attention-error",
      severity: "error",
      kind: "generation",
      title: "Generation requires review",
      occurred_at: "2026-07-13T07:59:00Z",
      action_url: "/jobs?status=needs_review",
    },
    {
      id: "attention-warning",
      severity: "warning",
      kind: "job",
      title: "Queue is approaching its limit",
      occurred_at: "2026-07-13T07:58:00Z",
      action_url: "/jobs?status=queued",
    },
  ],
  outbound_proxy: {
    mode: "direct",
    scheme: null,
    bypass_rule_count: 0,
    last_connectivity_status: "not_checked",
    configuration_error_code: null,
  },
} satisfies components["schemas"]["OperationsSnapshotOut"]

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    test.describe(`${viewport.label} ${theme} accessibility`, () => {
      for (const route of ROUTES) {
        test(`${route.name} has no serious or critical axe violations`, async ({ page }) => {
          const unhandledRequests = await installMockBackend(page)
          await page.setViewportSize(viewport)
          await page.goto(route.path)
          await page.evaluate((selectedTheme) => {
            document.documentElement.classList.toggle("dark", selectedTheme === "dark")
          }, theme)

          await expect(page.getByRole("heading", { name: route.name, exact: true }).first()).toBeVisible()
          await expect(page.getByText(route.readyText, { exact: true }).first()).toBeVisible()
          expect(unhandledRequests, `Unhandled backend requests on ${route.path}`).toEqual([])

          const results = await new AxeBuilder({ page }).analyze()
          const violations = results.violations
            .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
            .map((violation) => ({
              id: violation.id,
              impact: violation.impact,
              help: violation.help,
              targets: violation.nodes.flatMap((node) => node.target),
            }))

          expect(violations).toEqual([])
        })
      }

      test("Diagnostics status palettes have no serious or critical axe violations", async ({ page }) => {
        const unhandledRequests = await installMockBackend(page, { operations: DIAGNOSTICS_STATUS_FIXTURE })
        await page.setViewportSize(viewport)
        await page.goto("/diagnostics")
        await setTheme(page, theme)
        for (const status of ["healthy", "degraded", "down", "unknown", "error", "warning"]) {
          await expect(page.getByText(status, { exact: true }).first()).toBeVisible()
        }
        expect(unhandledRequests).toEqual([])
        await expectNoSeriousAxeViolations(page)
      })

      test("Diagnostics loading state has no serious or critical axe violations", async ({ page }) => {
        await installMockBackend(page, { operationsDelayMs: 10_000 })
        await page.setViewportSize(viewport)
        await page.goto("/diagnostics")
        await setTheme(page, theme)
        await expect(page.getByRole("status", { name: "Loading operational diagnostics" })).toBeVisible()
        await expectNoSeriousAxeViolations(page)
      })

      test("Diagnostics API-error state has no serious or critical axe violations", async ({ page }) => {
        await installMockBackend(page, { operationsFailure: true })
        await page.setViewportSize(viewport)
        await page.goto("/diagnostics")
        await setTheme(page, theme)
        await expect(page.getByRole("alert")).toBeVisible()
        await expectNoSeriousAxeViolations(page)
      })
    })
  }
}

async function setTheme(page: import("@playwright/test").Page, theme: (typeof THEMES)[number]) {
  await page.evaluate((selectedTheme) => {
    document.documentElement.classList.toggle("dark", selectedTheme === "dark")
  }, theme)
}

async function expectNoSeriousAxeViolations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).analyze()
  const violations = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      targets: violation.nodes.flatMap((node) => node.target),
    }))
  expect(violations).toEqual([])
}

test("responsive shell switches at 900px and exposes one skip target", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page)

  await page.setViewportSize({ width: 899, height: 844 })
  await page.goto("/")
  await expect(page.getByText("No workflow jobs yet", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "Newsroom navigation", exact: true })).toBeHidden()

  const skipLink = page.getByRole("link", { name: "Skip to content" })
  const main = page.getByRole("main")
  await expect(skipLink).toHaveAttribute("href", "#main-content")
  await expect(main).toHaveCount(1)
  await expect(main).toHaveAttribute("id", "main-content")
  await expect(main).toHaveAttribute("tabindex", "-1")
  await page.keyboard.press("Tab")
  await expect(skipLink).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(main).toBeFocused()

  await page.setViewportSize({ width: 900, height: 844 })
  await expect(page.getByRole("navigation", { name: "Newsroom navigation", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeHidden()
  expect(unhandledRequests, "Unhandled backend requests in responsive shell test").toEqual([])
})

test("primary Inbox actions provide 44 by 44 pixel touch targets on mobile", async ({ page }) => {
  const unhandledRequests = await installMockBackend(page, { stories: [MOBILE_ACTION_STORY] })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/inbox")
  await expect(page.getByText("Election timeline", { exact: true })).toBeVisible()

  const targets = [
    page.getByRole("button", { name: "Group pending content", exact: true }),
    page.getByRole("button", { name: "Add story", exact: true }),
    page.getByRole("button", { name: "Open Election timeline", exact: true }),
    page.getByRole("button", { name: "Shortlist", exact: true }),
    page.getByRole("button", { name: "Reject", exact: true }),
    page.getByRole("button", { name: "Research more", exact: true }),
    page.getByRole("link", { name: "Open editorial studio", exact: true }),
  ]

  for (const target of targets) {
    const box = await target.boundingBox()
    expect(box, `Missing rendered target for ${await target.getAttribute("aria-label") ?? await target.textContent()}`).not.toBeNull()
    expect(box!.width).toBeGreaterThanOrEqual(44)
    expect(box!.height).toBeGreaterThanOrEqual(44)
  }
  expect(unhandledRequests, "Unhandled backend requests in mobile target test").toEqual([])
})
