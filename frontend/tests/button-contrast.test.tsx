import { buttonVariants } from "@/components/ui/button"

it("uses the semantic high-contrast palette for destructive actions", () => {
  const classes = buttonVariants({ variant: "destructive" })

  expect(classes).toContain("bg-[var(--error-surface)]")
  expect(classes).toContain("text-destructive")
  expect(classes).toContain("border-destructive/25")
  expect(classes).not.toContain("bg-destructive/10")
  expect(classes).not.toMatch(/(?:bg|text|border)-red-/)
})
