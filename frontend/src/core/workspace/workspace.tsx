import { RouterProvider, useRouter, useRouterState } from '@tanstack/react-router'
import { Columns2Icon, PlusIcon, XIcon } from 'lucide-react'
import {
  Fragment,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { PaneContext, PaneRouterContext } from './context'
import { routeOf } from './links'
import { useWorkspace, type Pane, type Workspace as WorkspaceState } from './store'
import { TabTitle } from './tab-title'

const STEP = 0.05

/** Opens pages in the workspace from the pane this renders in (the main pane outside panes). */
export function useOpenIn(vault: string) {
  const current = useContext(PaneContext)
  const pane = () => current ?? useWorkspace.getState().byVault[vault]?.panes[0]?.id
  return {
    /** Opens `href` in a new tab of this pane. */
    newTab: (href: string) => {
      const id = pane()
      if (id !== undefined) useWorkspace.getState().openTab(vault, id, href)
    },
    /** Opens `href` in a pane to the right of this one. */
    toTheRight: (href: string) => {
      const id = pane()
      if (id !== undefined) useWorkspace.getState().split(vault, id, href)
    },
  }
}

/**
 * Keeps the main pane and the address bar together: a navigation moves the main pane's tab, and
 * showing another tab there (or closing the shown one) navigates.
 */
function useMainPaneSync(vault: string) {
  const router = useRouter()
  const href = useRouterState({ select: (state) => state.location.href })
  useLayoutEffect(() => {
    useWorkspace.getState().follow(vault, href)
  }, [vault, href])
  useEffect(
    () =>
      useWorkspace.subscribe((state) => {
        const main = state.byVault[vault]?.panes[0]
        const shown = main?.tabs.find((tab) => tab.id === main.active)
        if (shown !== undefined && shown.href !== router.state.location.href) {
          router.history.push(shown.href)
        }
      }),
    [vault, router],
  )
}

/** Alt-click on a link opens it in a new tab of its pane; Alt+Shift-click, to the right. */
function useAltClick(vault: string) {
  useEffect(() => {
    const onClick = (event: MouseEvent): void => {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.button !== 0) return
      const target = event.target instanceof Element ? event.target : null
      const anchor = target?.closest('a')
      const route = anchor ? routeOf(anchor, vault) : null
      if (route === null) return
      const state = useWorkspace.getState()
      const pane =
        target?.closest<HTMLElement>('[data-pane]')?.dataset.pane ??
        state.byVault[vault]?.panes[0]?.id
      if (pane === undefined) return
      event.preventDefault()
      event.stopPropagation()
      if (event.shiftKey) state.split(vault, pane, route)
      else state.openTab(vault, pane, route)
    }
    document.addEventListener('click', onClick, true)
    return () => {
      document.removeEventListener('click', onClick, true)
    }
  }, [vault])
}

/** A pane beside the main one: its own router, at its tab's page; it reports where it goes. */
function PaneRouter({
  vault,
  pane,
  tab,
  href,
}: {
  vault: string
  pane: string
  tab: string
  href: string
}) {
  const create = useContext(PaneRouterContext)
  const [created] = useState(() => create?.(href) ?? null)
  useEffect(() => {
    if (created === null) return
    const { history } = created
    return history.subscribe(() => {
      useWorkspace.getState().setHref(vault, pane, tab, history.location.href)
    })
  }, [created, vault, pane, tab])
  if (created === null) return null
  return (
    <PaneContext value={pane}>
      <RouterProvider router={created.router} />
    </PaneContext>
  )
}

function TabStrip({
  vault,
  pane,
  index,
  workspace,
}: {
  vault: string
  pane: Pane
  index: number
  workspace: WorkspaceState
}) {
  const state = useWorkspace.getState()
  const only = workspace.panes.length === 1 && pane.tabs.length === 1
  const shown = pane.tabs.find((tab) => tab.id === pane.active)
  return (
    <div data-tab-strip className="hidden h-9 shrink-0 items-stretch border-b bg-muted/40 md:flex">
      <ul
        aria-label={index === 0 ? 'Tabs' : `Tabs of pane ${String(index + 1)}`}
        className="flex min-w-0 flex-1 overflow-x-auto"
      >
        {pane.tabs.map((tab) => {
          const active = tab.id === pane.active
          return (
            <li
              key={tab.id}
              className={cn(
                'group flex max-w-56 min-w-0 shrink-0 items-center border-r text-sm',
                active ? 'bg-background font-medium' : 'text-muted-foreground hover:bg-accent',
              )}
            >
              <button
                type="button"
                aria-current={active ? 'page' : undefined}
                className="min-w-0 truncate py-1.5 pr-1 pl-3 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset"
                onClick={() => {
                  state.showTab(vault, pane.id, tab.id)
                }}
                onAuxClick={(event) => {
                  if (event.button !== 1 || only) return
                  event.preventDefault()
                  state.closeTab(vault, pane.id, tab.id)
                }}
              >
                <TabTitle vault={vault} href={tab.href} />
              </button>
              {!only && (
                <button
                  type="button"
                  aria-label="Close tab"
                  title="Close tab"
                  className="mr-1 rounded p-0.5 text-muted-foreground opacity-60 group-hover:opacity-100 hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  onClick={() => {
                    state.closeTab(vault, pane.id, tab.id)
                  }}
                >
                  <XIcon className="size-3.5" aria-hidden />
                </button>
              )}
            </li>
          )
        })}
      </ul>
      <Button
        variant="ghost"
        size="icon"
        className="size-9 rounded-none"
        aria-label="New tab"
        title="New tab"
        onClick={() => {
          state.openTab(vault, pane.id, `/v/${vault}`)
        }}
      >
        <PlusIcon />
      </Button>
      {shown !== undefined && (
        <Button
          variant="ghost"
          size="icon"
          className="size-9 rounded-none"
          aria-label="Open to the right"
          title="Open this page to the right"
          onClick={() => {
            state.split(vault, pane.id, shown.href)
          }}
        >
          <Columns2Icon />
        </Button>
      )}
      {workspace.panes.length > 1 && (
        <Button
          variant="ghost"
          size="icon"
          className="size-9 rounded-none"
          aria-label="Close pane"
          title="Close pane"
          onClick={() => {
            state.closePane(vault, pane.id)
          }}
        >
          <XIcon />
        </Button>
      )}
    </div>
  )
}

/** The border between pane `index` and the next: drag it, or focus it and use ← →. */
function PaneResizer({ vault, index, share }: { vault: string; index: number; share: number }) {
  const resize = (delta: number) => {
    useWorkspace.getState().resize(vault, index, delta)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const delta = { ArrowLeft: -STEP, ArrowRight: STEP }[event.key]
    if (delta === undefined) return
    event.preventDefault()
    resize(delta)
  }
  const onPointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    event.preventDefault()
    const target = event.currentTarget
    const width = target.closest('[data-workspace]')?.getBoundingClientRect().width ?? 0
    if (width <= 0) return
    let lastX = event.clientX
    target.setPointerCapture(event.pointerId)
    const onMove = (move: globalThis.PointerEvent): void => {
      resize((move.clientX - lastX) / width)
      lastX = move.clientX
    }
    const onUp = (): void => {
      target.removeEventListener('pointermove', onMove)
      target.removeEventListener('pointerup', onUp)
    }
    target.addEventListener('pointermove', onMove)
    target.addEventListener('pointerup', onUp)
  }
  return (
    // A focusable separator is the ARIA "window splitter" pattern: it is interactive.
    // eslint-disable-next-line jsx-a11y-x/no-noninteractive-element-interactions
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize pane ${String(index + 1)}`}
      aria-valuenow={Math.round(share * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex -- window splitter (see above)
      tabIndex={0}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      className="hidden w-1 shrink-0 cursor-col-resize bg-border transition-colors hover:bg-ring focus-visible:bg-ring focus-visible:outline-none md:block"
    />
  )
}

/**
 * The main area as a workspace (frontend.md §3): panes side by side, each with tabs. The first
 * pane is the main one: it renders `children` (the current route) and its tab follows the
 * address bar. The others each run their own router.
 */
export function Workspace({ vault, children }: { vault: string; children: ReactNode }) {
  const workspace = useWorkspace((state) => state.byVault[vault])
  useMainPaneSync(vault)
  useAltClick(vault)
  const panes = workspace?.panes ?? []
  return (
    <div data-workspace className="flex min-h-0 flex-col md:h-full md:flex-row">
      {(panes.length > 0 ? panes : [null]).map((pane, index) => {
        const shown = pane?.tabs.find((tab) => tab.id === pane.active)
        return (
          // The main pane keeps its key, so the current route stays mounted when panes change.
          <Fragment key={index === 0 ? 'main' : (pane?.id ?? index)}>
            {index > 0 && (
              <PaneResizer
                vault={vault}
                index={index - 1}
                share={workspace?.sizes[index - 1] ?? 0}
              />
            )}
            <section
              aria-label={index === 0 ? 'Main pane' : `Pane ${String(index + 1)}`}
              data-pane={pane?.id}
              className={cn(
                'min-h-0 min-w-0 flex-col md:basis-0',
                // Narrow screens show the main pane alone, without tabs.
                index === 0 ? 'flex' : 'hidden md:flex',
              )}
              style={{ flexGrow: workspace?.sizes[index] ?? 1 }}
            >
              {pane !== null && workspace !== undefined && (
                <TabStrip vault={vault} pane={pane} index={index} workspace={workspace} />
              )}
              <div className="min-h-0 flex-1 md:overflow-auto">
                {index === 0 ? (
                  children
                ) : pane !== null && shown !== undefined ? (
                  <PaneRouter
                    key={shown.id}
                    vault={vault}
                    pane={pane.id}
                    tab={shown.id}
                    href={shown.href}
                  />
                ) : null}
              </div>
            </section>
          </Fragment>
        )
      })}
    </div>
  )
}
