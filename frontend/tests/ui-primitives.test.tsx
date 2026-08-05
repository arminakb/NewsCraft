import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"

import { NoticeProvider, useNotices } from "@/components/providers/notice-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Checkbox, Radio } from "@/components/ui/checkbox"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { PageHeader } from "@/components/ui/page-header"
import { Select } from "@/components/ui/select"
import { EmptyState, LoadingState } from "@/components/ui/state-panel"
import { StatusBadge } from "@/components/ui/status-badge"
import { Textarea } from "@/components/ui/textarea"

describe("shared UI primitives", () => {
  it("keeps form controls native, labelled, and invalid-state aware", () => {
    render(
      <form>
        <label htmlFor="headline">Headline</label>
        <Input aria-invalid="true" id="headline" />
        <label htmlFor="channel">Channel</label>
        <Select id="channel"><option>Telegram</option></Select>
        <label htmlFor="notes">Notes</label>
        <Textarea id="notes" />
        <label><Checkbox defaultChecked /> Include media</label>
        <label><Radio name="mode" defaultChecked /> Review first</label>
      </form>,
    )

    expect(screen.getByRole("textbox", { name: "Headline" })).toHaveAttribute("data-slot", "input")
    expect(screen.getByRole("textbox", { name: "Headline" })).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("combobox", { name: "Channel" })).toHaveAttribute("data-slot", "select")
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveAttribute("data-slot", "textarea")
    expect(screen.getByRole("checkbox", { name: "Include media" })).toBeChecked()
    expect(screen.getByRole("radio", { name: "Review first" })).toBeChecked()
  })

  it("renders semantic feedback, status, state, and page-header content", () => {
    render(
      <>
        <PageHeader title="Jobs" titleId="jobs-title" description="Durable workflow state" />
        <StatusBadge tone="success">Healthy</StatusBadge>
        <Alert tone="error" role="alert">
          <div><AlertTitle>Request failed</AlertTitle><AlertDescription>Retry the request.</AlertDescription></div>
        </Alert>
        <EmptyState title="No jobs" description="Change the current filter." />
        <LoadingState aria-label="Loading jobs" />
      </>,
    )

    expect(screen.getByRole("heading", { level: 1, name: "Jobs" })).toHaveAttribute("id", "jobs-title")
    expect(screen.getByText("Healthy").closest("[data-slot='badge']")).toHaveClass("text-success")
    expect(screen.getByRole("alert")).toHaveTextContent("Request failed")
    expect(screen.getByRole("heading", { level: 3, name: "No jobs" })).toBeInTheDocument()
    expect(screen.getByRole("status", { name: "Loading jobs" })).toBeInTheDocument()
  })

  it("traps dialog semantics and restores focus when closed", async () => {
    render(<DialogHarness />)

    const trigger = screen.getByRole("button", { name: "Open settings" })
    trigger.focus()
    fireEvent.click(trigger)

    const dialog = await screen.findByRole("dialog", { name: "Edit settings" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(dialog).toHaveAccessibleDescription("Changes apply immediately.")

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it("preserves button variant APIs for links and icon controls", () => {
    render(<Button aria-label="Refresh" size="icon" variant="outline">R</Button>)
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveClass("min-h-11")
    expect(buttonVariants({ variant: "destructive" })).toContain("text-destructive")
  })

  it("announces and dismisses toast notices without stealing focus", () => {
    render(<NoticeProvider><NoticeHarness /></NoticeProvider>)

    const trigger = screen.getByRole("button", { name: "Save" })
    trigger.focus()
    fireEvent.click(trigger)

    expect(screen.getByRole("status", { name: "Notifications" })).toHaveAttribute("aria-live", "polite")
    expect(screen.getByText("Saved")).toBeInTheDocument()
    expect(trigger).toHaveFocus()
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Saved" }))
    expect(screen.queryByText("Saved")).not.toBeInTheDocument()
  })

})

function DialogHarness() {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger>Open settings</DialogTrigger>
      <DialogContent>
        <DialogTitle>Edit settings</DialogTitle>
        <DialogDescription>Changes apply immediately.</DialogDescription>
        <DialogClose>Cancel</DialogClose>
      </DialogContent>
    </Dialog>
  )
}

function NoticeHarness() {
  const { pushNotice } = useNotices()
  return <button onClick={() => pushNotice({ tone: "success", title: "Saved", message: "Settings stored." })}>Save</button>
}
