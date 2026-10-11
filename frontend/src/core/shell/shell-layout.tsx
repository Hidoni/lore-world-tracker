import { useParams } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { BacklinksPanel } from '@/core/links'
import { CommandPalette, ShortcutsDialog } from '@/core/palette'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'

import { useShell } from './shell-store'
import { SidebarResizer } from './sidebar-resizer'
import { TopBar } from './top-bar'
import { VaultNav } from './vault-nav'

/** The context panel's content for the current page: an entity's backlinks and mentions. */
function ContextPanel() {
  const { vault, entity } = useParams({ strict: false })
  if (vault === undefined || entity === undefined) {
    return (
      <>
        <h2 className="mb-2 font-medium text-foreground">Context</h2>
        <p>Backlinks, outline, findings and history for the current page appear here.</p>
      </>
    )
  }
  return <BacklinksPanel key={entity} vault={vault} entityId={entity} />
}

/**
 * The app shell (frontend.md §3): top bar, resizable and collapsible sidebar, main area and a
 * collapsible context panel. Below `md` the sidebar is a drawer and the context panel follows the
 * content.
 */
export function ShellLayout({ children }: { children: ReactNode }) {
  const sidebarOpen = useShell((state) => state.sidebarOpen)
  const sidebarWidth = useShell((state) => state.sidebarWidth)
  const rightPanelOpen = useShell((state) => state.rightPanelOpen)
  const drawerOpen = useShell((state) => state.drawerOpen)
  const setDrawerOpen = useShell((state) => state.setDrawerOpen)

  return (
    <div className="flex h-svh flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:ring-2 focus:ring-ring"
      >
        Skip to content
      </a>
      <TopBar />
      <div className="flex min-h-0 flex-1 flex-col overflow-auto md:flex-row md:overflow-hidden">
        {sidebarOpen && (
          <>
            <aside
              id="sidebar"
              aria-label="Sidebar"
              className="hidden shrink-0 overflow-y-auto border-r md:block"
              style={{ width: sidebarWidth }}
            >
              <VaultNav />
            </aside>
            <div className="hidden md:flex">
              <SidebarResizer />
            </div>
          </>
        )}
        <main
          id="main"
          tabIndex={-1}
          className="min-w-0 flex-1 focus:outline-none md:overflow-auto"
        >
          {children}
        </main>
        {rightPanelOpen && (
          <aside
            id="context-panel"
            aria-label="Context"
            className="shrink-0 border-t p-4 text-sm text-muted-foreground md:w-72 md:overflow-y-auto md:border-t-0 md:border-l"
          >
            <ContextPanel />
          </aside>
        )}
      </div>
      <CommandPalette />
      <ShortcutsDialog />
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="left" className="w-72">
          <SheetTitle className="px-4 pt-4">Navigation</SheetTitle>
          <SheetDescription className="sr-only">The vault's pages.</SheetDescription>
          <VaultNav
            onNavigate={() => {
              setDrawerOpen(false)
            }}
          />
        </SheetContent>
      </Sheet>
    </div>
  )
}
