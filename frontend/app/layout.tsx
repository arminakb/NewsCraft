import type { Metadata } from "next"

import "./globals.css"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { DirtyNavigationCoordinator } from "@/components/editorial/use-dirty-navigation"
import { QueryProvider } from "@/components/providers/query-provider"
import { ThemeProvider } from "@/components/providers/theme-provider"
import { NewsroomShell } from "@/components/newsroom/newsroom-shell"
import { TooltipProvider } from "@/components/ui/tooltip"
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme"

export const metadata: Metadata = {
  title: "NewsCraft",
  description: "Local content operations command center",
}

export default function RootLayout({
  children,
  settings,
}: Readonly<{
  children: React.ReactNode
  settings?: React.ReactNode
}>) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }}
          id="newscraft-theme-init"
        />
      </head>
      <body>
        <a href="#main-content" className="skip-link">
          Skip to content
        </a>
        <DirtyNavigationCoordinator />
        <QueryProvider>
          <TooltipProvider>
            <ThemeProvider>
              <NoticeProvider>
                <NewsroomShell settings={settings}>{children}</NewsroomShell>
              </NoticeProvider>
            </ThemeProvider>
          </TooltipProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
