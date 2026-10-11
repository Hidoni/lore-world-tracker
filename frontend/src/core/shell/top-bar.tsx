import { Link, useParams } from '@tanstack/react-router'
import {
  LibraryIcon,
  MenuIcon,
  PanelLeftIcon,
  PanelRightIcon,
  SearchIcon,
  SettingsIcon,
} from 'lucide-react'
import { useEffect } from 'react'

import { ThemeMenu } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'
import { isTyping, usePalette } from '@/core/palette'
import { NewEntityMenu } from '@/core/entities'
import { useVault } from '@/data'

import { useShell } from './shell-store'

function VaultSwitcher({ vault }: { vault: string }) {
  const found = useVault(vault)
  return (
    <Button variant="ghost" size="sm" asChild>
      <Link to="/" search={{ pick: true }} title="Switch vault">
        <LibraryIcon aria-hidden />
        <span className="max-w-40 truncate">{found.data?.name ?? 'Vault'}</span>
      </Link>
    </Button>
  )
}

/**
 * Ctrl/Cmd+K toggles the command palette (in a vault) and `?` opens the shortcuts sheet, outside
 * text fields and the editor.
 */
function useGlobalShortcuts(vault: string | undefined) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      const palette = usePalette.getState()
      if (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey)) {
        if (vault === undefined) return
        event.preventDefault()
        palette.setOpen(!palette.open)
      } else if (event.key === '?' && !event.ctrlKey && !event.metaKey && !isTyping(event.target)) {
        event.preventDefault()
        palette.setShortcutsOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [vault])
}

/** The shell's top bar (frontend.md §3). Dimension, timeline and time controls arrive with M5. */
export function TopBar() {
  const { vault } = useParams({ strict: false })
  const sidebarOpen = useShell((state) => state.sidebarOpen)
  const rightPanelOpen = useShell((state) => state.rightPanelOpen)
  const toggleSidebar = useShell((state) => state.toggleSidebar)
  const toggleRightPanel = useShell((state) => state.toggleRightPanel)
  const setDrawerOpen = useShell((state) => state.setDrawerOpen)
  useGlobalShortcuts(vault)

  return (
    <header className="flex h-12 shrink-0 items-center gap-1 border-b px-2">
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        aria-label="Open navigation"
        onClick={() => {
          setDrawerOpen(true)
        }}
      >
        <MenuIcon />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="hidden md:inline-flex"
        aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
        aria-expanded={sidebarOpen}
        aria-controls="sidebar"
        onClick={toggleSidebar}
      >
        <PanelLeftIcon />
      </Button>
      <Link to="/" search={{ pick: true }} className="px-2 font-semibold whitespace-nowrap">
        Lore
      </Link>
      {vault !== undefined && (
        <>
          <VaultSwitcher vault={vault} />
          <Button variant="ghost" size="sm" disabled title="Dimensions arrive with M5">
            Dimension
          </Button>
        </>
      )}
      <div className="flex-1" />
      {vault !== undefined && (
        <>
          <NewEntityMenu vault={vault} />
          <Button
            variant="outline"
            size="sm"
            aria-keyshortcuts="Control+K Meta+K"
            onClick={() => {
              usePalette.getState().setOpen(true)
            }}
          >
            <SearchIcon aria-hidden />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden text-xs text-muted-foreground sm:inline">Ctrl K</kbd>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={rightPanelOpen ? 'Hide context panel' : 'Show context panel'}
            aria-expanded={rightPanelOpen}
            aria-controls="context-panel"
            onClick={toggleRightPanel}
          >
            <PanelRightIcon />
          </Button>
          <Button variant="ghost" size="icon" asChild>
            <Link to="/v/$vault/settings" params={{ vault }} aria-label="Settings">
              <SettingsIcon />
            </Link>
          </Button>
        </>
      )}
      <ThemeMenu />
    </header>
  )
}
