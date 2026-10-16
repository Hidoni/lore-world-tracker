import {
  createElement,
  lazy,
  Suspense,
  useEffect,
  useState,
  type ComponentType,
  type FunctionComponent,
  type ReactNode,
} from 'react'

import { collectList } from './activation'
import { useActiveModules } from './context'
import type { EditorExtension, EditorExtensionLoader, ModuleDefinition } from './types'

/** A component loaded on demand that can be loaded ahead (`preload`), e.g. when the app is idle. */
export interface LazyComponent<P extends object> extends FunctionComponent<P> {
  preload: () => Promise<void>
}

/**
 * A component whose code is loaded with the first page that shows it (frontend.md §12), or
 * earlier through `preload` (the vault preloads the modules' entity panels when idle). Once
 * loaded it renders at once: no Suspense, so no fallback and none of React's delay before
 * revealing what a fallback stood for (300 ms), which a page of lazy panels would otherwise wait.
 */
export function lazyComponent<P extends object>(
  load: () => Promise<ComponentType<P>>,
  fallback: ReactNode = null,
): LazyComponent<P> {
  let loaded: ComponentType<P> | undefined
  let pending: Promise<void> | undefined
  const preload = () =>
    (pending ??= load().then(
      (component) => {
        loaded = component
      },
      (error: unknown) => {
        pending = undefined // the next page that shows it tries again
        throw error
      },
    ))
  const Lazy = lazy(async () => {
    await preload()
    if (loaded === undefined) throw new Error('lazyComponent: nothing loaded')
    return { default: loaded }
  })
  function Component(props: P) {
    // Decided once per mount: switching to the loaded component later would remount it.
    const [ready] = useState(() => loaded)
    if (ready !== undefined) return createElement(ready, props)
    return createElement(Suspense, { fallback }, createElement(Lazy, props))
  }
  Component.preload = preload
  return Component
}

/** Whether a component is a `lazyComponent` (it can be preloaded). */
export function isLazyComponent(component: unknown): component is LazyComponent<object> {
  return (
    typeof component === 'function' &&
    typeof (component as Partial<LazyComponent<object>>).preload === 'function'
  )
}

/** A promise React's `use()` reads without suspending once it has settled. */
type Tracked<T> = Promise<T> & { status?: 'pending' | 'fulfilled' | 'rejected'; value?: T }

function tracked<T>(promise: Promise<T>): Tracked<T> {
  const result: Tracked<T> = promise
  result.status = 'pending'
  result.then(
    (value) => {
      result.status = 'fulfilled'
      result.value = value
    },
    () => {
      result.status = 'rejected'
    },
  )
  return result
}

const extensions = new Map<EditorExtensionLoader, Promise<EditorExtension>>()
const extensionSets = new Map<string, Tracked<EditorExtension[]>>()
const loaderIds = new WeakMap<EditorExtensionLoader, number>()
let nextLoaderId = 0

/**
 * The modules' editor extensions (`editorExtensions` are loaders), each loaded once. The promise
 * for a set of loaders is cached and marked when it settles, so `use()` sees the same one after it
 * suspends, and none at all once the set was preloaded.
 */
export function loadEditorExtensions(
  loaders: readonly EditorExtensionLoader[],
): Promise<EditorExtension[]> {
  const key = loaders
    .map((loader) => {
      let id = loaderIds.get(loader)
      if (id === undefined) {
        nextLoaderId += 1
        id = nextLoaderId
        loaderIds.set(loader, id)
      }
      return id
    })
    .join(',')
  let found = extensionSets.get(key)
  if (found === undefined) {
    found = tracked(
      Promise.all(
        loaders.map((loader) => {
          let one = extensions.get(loader)
          if (one === undefined) {
            one = loader()
            extensions.set(loader, one)
            one.catch(() => {
              extensions.delete(loader) // tried again next time
              extensionSets.delete(key)
            })
          }
          return one
        }),
      ),
    )
    extensionSets.set(key, found)
  }
  return found
}

/**
 * The lazy components of a module's extension points: list entries and keyed values that are one,
 * or that hold one as their `component` (entity panels, header media, timeline layers, …).
 */
function lazyComponentsOf(module: ModuleDefinition): LazyComponent<object>[] {
  const found: LazyComponent<object>[] = []
  for (const point of Object.values(module) as unknown[]) {
    if (typeof point !== 'object' || point === null) continue
    const entries: unknown[] = Array.isArray(point) ? point : Object.values(point)
    for (const entry of entries) {
      const component =
        typeof entry === 'object' && entry !== null
          ? (entry as { component?: unknown }).component
          : entry
      if (isLazyComponent(component)) found.push(component)
    }
  }
  return found
}

/** Runs `task` when the browser is idle (soon after, where `requestIdleCallback` is missing). */
function whenIdle(task: () => void): () => void {
  if (typeof window.requestIdleCallback === 'function') {
    const handle = window.requestIdleCallback(task, { timeout: 2000 })
    return () => {
      window.cancelIdleCallback(handle)
    }
  }
  const handle = window.setTimeout(task, 200)
  return () => {
    window.clearTimeout(handle)
  }
}

/**
 * Loads the code of the vault's active modules ahead, when the browser is idle: every lazy
 * component of their extension points (entity panels, header items, dimension sections, timeline
 * layers, …) and their editor extensions, plus `extra` (e.g. the editor). Pages then show them at
 * once instead of loading them first.
 */
const NO_EXTRA: readonly (() => unknown)[] = []

export function usePreloadModules(vault: string, extra = NO_EXTRA): void {
  const { modules } = useActiveModules(vault)
  useEffect(() => {
    if (modules.length === 0) return
    return whenIdle(() => {
      const failed = () => undefined // loaded again (and reported) when a page needs it
      for (const module of modules) {
        for (const component of lazyComponentsOf(module)) component.preload().catch(failed)
      }
      loadEditorExtensions(collectList(modules, 'editorExtensions')).catch(failed)
      for (const load of extra) Promise.resolve(load()).catch(failed)
    })
  }, [modules, extra])
}
