import type { ReactNode } from 'react'

import { ThemeToggle } from '@/components/theme-toggle'

/** Placeholder app shell (top bar + main area). The full shell arrives with frontend.md §3. */
export function ShellLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex h-12 items-center justify-between border-b px-4">
        <span className="font-semibold">Lore World Tracker</span>
        <ThemeToggle />
      </header>
      <main className="flex-1">{children}</main>
    </div>
  )
}
