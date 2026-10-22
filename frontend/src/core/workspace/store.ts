import { create } from 'zustand'

import { readStored, writeStored } from '@/lib/storage'

/** The most panes side by side (frontend.md §3). */
export const MAX_PANES = 4
/** The narrowest a pane gets, as a share of the workspace's width. */
const MIN_SHARE = 0.15
const STORAGE_PREFIX = 'lore.workspace.'

/** A tab: one page of the vault, by its path and search (`/v/<vault>/e/<id>?tab=…`). */
export interface Tab {
  id: string
  href: string
}

/** A pane: its tabs and the one it shows. */
export interface Pane {
  id: string
  tabs: Tab[]
  active: string
}

/**
 * A vault's workspace: panes side by side, each with tabs, and their widths (shares summing to
 * 1). The first pane is the main one: its tab follows the address bar.
 */
export interface Workspace {
  panes: Pane[]
  sizes: number[]
}

let counter = 0
const newId = (prefix: string): string =>
  `${prefix}${Date.now().toString(36)}${(counter++).toString(36)}`

const equalSizes = (count: number): number[] => Array.from({ length: count }, () => 1 / count)

function newPane(href: string): Pane {
  const tab = { id: newId('t'), href }
  return { id: newId('p'), tabs: [tab], active: tab.id }
}

/** A stored workspace, or `null` when it is missing or doesn't parse. */
function parse(text: string | null): Workspace | null {
  if (text === null) return null
  try {
    const value = JSON.parse(text) as { panes?: unknown; sizes?: unknown }
    if (!Array.isArray(value.panes)) return null
    const panes: Pane[] = []
    for (const raw of value.panes.slice(0, MAX_PANES) as Partial<Pane>[]) {
      const tabs = (Array.isArray(raw.tabs) ? raw.tabs : []).filter(
        (tab): tab is Tab => typeof tab.id === 'string' && typeof tab.href === 'string',
      )
      const first = tabs[0]
      if (typeof raw.id !== 'string' || first === undefined) continue
      const active = tabs.find((tab) => tab.id === raw.active)?.id ?? first.id
      panes.push({ id: raw.id, tabs, active })
    }
    if (panes.length === 0) return null
    const sizes =
      Array.isArray(value.sizes) &&
      value.sizes.length === panes.length &&
      value.sizes.every((size) => typeof size === 'number' && size > 0)
        ? normalize(value.sizes as number[])
        : equalSizes(panes.length)
    return { panes, sizes }
  } catch {
    return null
  }
}

function normalize(sizes: readonly number[]): number[] {
  const total = sizes.reduce((sum, size) => sum + size, 0)
  return sizes.map((size) => size / total)
}

/** `sizes` with pane `index` removed, its share going to its neighbours. */
function withoutSize(sizes: readonly number[], index: number): number[] {
  return normalize(sizes.filter((_, at) => at !== index))
}

/** `sizes` with a pane inserted at `index`, halving the pane it splits from. */
function withSize(sizes: readonly number[], index: number): number[] {
  const from = Math.max(0, index - 1)
  const half = (sizes[from] ?? 1) / 2
  const next = sizes.map((size, at) => (at === from ? half : size))
  next.splice(index, 0, half)
  return normalize(next)
}

interface WorkspaceState {
  /** Workspaces by vault, loaded from `localStorage` on first use. */
  byVault: Record<string, Workspace>
  /** The vault's workspace, with one tab at `href` when it has none yet. */
  get: (vault: string, href: string) => Workspace
  /** The main pane's tab follows the address bar: a tab already there is shown, otherwise the
   * shown tab moves there. */
  follow: (vault: string, href: string) => void
  /** A pane's tab went elsewhere. */
  setHref: (vault: string, pane: string, tab: string, href: string) => void
  /** Opens `href` in a new tab after the pane's current one, and shows it. */
  openTab: (vault: string, pane: string, href: string) => Tab
  /** Opens `href` in a new pane after `after`, or as a new tab of the next pane when there are
   * `MAX_PANES` already. Returns the pane it opened in. */
  split: (vault: string, after: string, href: string) => string
  showTab: (vault: string, pane: string, tab: string) => void
  /** Closes a tab (and its pane with its last tab; the last pane keeps one tab). */
  closeTab: (vault: string, pane: string, tab: string) => void
  closePane: (vault: string, pane: string) => void
  /** Moves the border after pane `index` by `delta` (a share of the width). */
  resize: (vault: string, index: number, delta: number) => void
  /** Re-reads the persisted workspaces (tests, another tab). */
  reload: () => void
}

/**
 * The tabbed, split workspace (frontend.md §3): per vault and browser, persisted in
 * `localStorage` (`lore.workspace.<vault>`).
 */
export const useWorkspace = create<WorkspaceState>()((set, get) => {
  const load = (vault: string, href: string): Workspace =>
    get().byVault[vault] ??
    parse(readStored(STORAGE_PREFIX + vault)) ?? { panes: [newPane(href)], sizes: [1] }

  const save = (vault: string, workspace: Workspace): void => {
    set({ byVault: { ...get().byVault, [vault]: workspace } })
    writeStored(STORAGE_PREFIX + vault, JSON.stringify(workspace))
  }

  const update = (vault: string, change: (workspace: Workspace) => Workspace | null): void => {
    const current = get().byVault[vault]
    if (current === undefined) return
    const next = change(current)
    if (next !== null && next !== current) save(vault, next)
  }

  const mapPane = (workspace: Workspace, id: string, change: (pane: Pane) => Pane): Workspace => ({
    ...workspace,
    panes: workspace.panes.map((pane) => (pane.id === id ? change(pane) : pane)),
  })

  return {
    byVault: {},
    get: (vault, href) => {
      const existing = get().byVault[vault]
      if (existing !== undefined) return existing
      const loaded = load(vault, href)
      set({ byVault: { ...get().byVault, [vault]: loaded } })
      return loaded
    },
    follow: (vault, href) => {
      const workspace = get().get(vault, href)
      const [main, ...rest] = workspace.panes
      if (main === undefined) return
      const shown = main.tabs.find((tab) => tab.id === main.active)
      if (shown?.href === href) return
      const open = main.tabs.find((tab) => tab.href === href)
      const next: Pane =
        open !== undefined
          ? { ...main, active: open.id }
          : {
              ...main,
              tabs: main.tabs.map((tab) => (tab.id === main.active ? { ...tab, href } : tab)),
            }
      save(vault, { ...workspace, panes: [next, ...rest] })
    },
    setHref: (vault, pane, tab, href) => {
      update(vault, (workspace) =>
        mapPane(workspace, pane, (found) => ({
          ...found,
          tabs: found.tabs.map((each) => (each.id === tab ? { ...each, href } : each)),
        })),
      )
    },
    openTab: (vault, pane, href) => {
      const tab = { id: newId('t'), href }
      update(vault, (workspace) =>
        mapPane(workspace, pane, (found) => {
          const tabs = [...found.tabs]
          tabs.splice(tabs.findIndex((each) => each.id === found.active) + 1, 0, tab)
          return { ...found, tabs, active: tab.id }
        }),
      )
      return tab
    },
    split: (vault, after, href) => {
      const workspace = get().byVault[vault]
      if (workspace === undefined) return after
      const index = workspace.panes.findIndex((pane) => pane.id === after) + 1
      if (workspace.panes.length >= MAX_PANES) {
        const target = workspace.panes[Math.min(index, workspace.panes.length - 1)]
        if (target === undefined) return after
        get().openTab(vault, target.id, href)
        return target.id
      }
      const pane = newPane(href)
      const panes = [...workspace.panes]
      panes.splice(index, 0, pane)
      save(vault, { panes, sizes: withSize(workspace.sizes, index) })
      return pane.id
    },
    showTab: (vault, pane, tab) => {
      update(vault, (workspace) => mapPane(workspace, pane, (found) => ({ ...found, active: tab })))
    },
    closeTab: (vault, pane, tab) => {
      update(vault, (workspace) => {
        const found = workspace.panes.find((each) => each.id === pane)
        if (found === undefined) return null
        const index = found.tabs.findIndex((each) => each.id === tab)
        if (index < 0) return null
        if (found.tabs.length === 1) {
          if (workspace.panes.length === 1) return null
          const at = workspace.panes.indexOf(found)
          return {
            panes: workspace.panes.filter((each) => each !== found),
            sizes: withoutSize(workspace.sizes, at),
          }
        }
        const tabs = found.tabs.filter((each) => each.id !== tab)
        // Closing the shown tab shows its right neighbour (or its left one at the end).
        const next = tabs[Math.min(index, tabs.length - 1)]
        const active = found.active === tab && next !== undefined ? next.id : found.active
        return mapPane(workspace, pane, () => ({ ...found, tabs, active }))
      })
    },
    closePane: (vault, pane) => {
      update(vault, (workspace) => {
        const at = workspace.panes.findIndex((each) => each.id === pane)
        if (at < 0 || workspace.panes.length === 1) return null
        return {
          panes: workspace.panes.filter((each) => each.id !== pane),
          sizes: withoutSize(workspace.sizes, at),
        }
      })
    },
    resize: (vault, index, delta) => {
      update(vault, (workspace) => {
        const left = workspace.sizes[index]
        const right = workspace.sizes[index + 1]
        if (left === undefined || right === undefined) return null
        const total = left + right
        if (total < 2 * MIN_SHARE) return null
        const nextLeft = Math.min(total - MIN_SHARE, Math.max(MIN_SHARE, left + delta))
        if (nextLeft === left) return null
        const sizes = [...workspace.sizes]
        sizes[index] = nextLeft
        sizes[index + 1] = total - nextLeft
        return { ...workspace, sizes }
      })
    },
    reload: () => {
      set({ byVault: {} })
    },
  }
})
