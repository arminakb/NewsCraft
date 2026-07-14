import { buttonVariants } from "@/components/ui/button"

it("uses an explicit high-contrast palette for destructive actions", () => {
  const classes = buttonVariants({ variant: "destructive" })

  expect(classes).toContain("bg-red-100")
  expect(classes).toContain("text-red-900")
  expect(classes).toContain("dark:bg-red-950")
  expect(classes).toContain("dark:text-red-100")
  expect(classes).not.toContain("bg-destructive/10")
})
