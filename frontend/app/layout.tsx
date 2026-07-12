import type { Metadata } from "next"

import "./globals.css"

import { QueryProvider } from "@/components/providers/query-provider"
import { NewsroomShell } from "@/components/newsroom/newsroom-shell"
import { TooltipProvider } from "@/components/ui/tooltip"

export const metadata: Metadata = {
  title: "NewsCraft",
  description: "Local content operations command center",
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          <TooltipProvider>
            <NewsroomShell>{children}</NewsroomShell>
          </TooltipProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
