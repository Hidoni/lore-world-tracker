import { create } from 'zustand'

import { readStored, writeStored } from '@/lib/storage'

export const SIDEBAR_MIN = 180
export const SIDEBAR_MAX = 480
export const SIDEBAR_DEFAULT = 256
const STORAGE_KEY = 'lore.shell'

interface Persisted {
  sidebarWidth: number
  sidebarOpen: boolean
  rightPanelOpen: boolean
}

const DEFAULTS: Persisted = {
  sidebarWidth: SIDEBAR_DEFAULT,
  sidebarOpen: true,
  rightPanelOpen: false,
}

export function clampWidth(width: number): number {
  return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(width)))
}

function load(): Persisted {
  const text = readStored(STORAGE_KEY)
  if (text === null) return DEFAULTS
  try {
    const value = JSON.parse(text) as Partial<Record<keyof Persisted, unknown>>
    return {
      sidebarWidth:
        typeof value.sidebarWidth === 'number'
          ? clampWidth(value.sidebarWidth)
          : DEFAULTS.sidebarWidth,
      sidebarOpen:
        typeof value.sidebarOpen === 'boolean' ? value.sidebarOpen : DEFAULTS.sidebarOpen,
      rightPanelOpen:
        typeof value.rightPanelOpen === 'boolean' ? value.rightPanelOpen : DEFAULTS.rightPanelOpen,
    }
  } catch {
    return DEFAULTS
  }
}

interface ShellState extends Persisted {
  /** The mobile navigation drawer (not persisted). */
  drawerOpen: boolean
  setSidebarWidth: (width: number) => void
  toggleSidebar: () => void
  toggleRightPanel: () => void
  setDrawerOpen: (open: boolean) => void
  /** Re-reads the persisted layout (tests, another tab). */
  reload: () => void
}

/** Shell layout state; the sidebar width and the open panels persist per browser. */
export const useShell = create<ShellState>()((set, get) => {
  const save = (patch: Partial<Persisted>): void => {
    set(patch)
    const { sidebarWidth, sidebarOpen, rightPanelOpen } = get()
    writeStored(STORAGE_KEY, JSON.stringify({ sidebarWidth, sidebarOpen, rightPanelOpen }))
  }
  return {
    ...load(),
    drawerOpen: false,
    setSidebarWidth: (width) => {
      save({ sidebarWidth: clampWidth(width) })
    },
    toggleSidebar: () => {
      save({ sidebarOpen: !get().sidebarOpen })
    },
    toggleRightPanel: () => {
      save({ rightPanelOpen: !get().rightPanelOpen })
    },
    setDrawerOpen: (open) => {
      set({ drawerOpen: open })
    },
    reload: () => {
      set({ ...load(), drawerOpen: false })
    },
  }
})
