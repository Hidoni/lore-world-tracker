import { useParams } from '@tanstack/react-router'
import { createContext, useContext, useMemo, type ReactNode } from 'react'

import { useRegistry } from '@/data'

import {
  activeModules,
  collectList,
  collectRecord,
  type ListPoint,
  type RecordPoint,
} from './activation'
import type { ModuleDefinition } from './types'

const DefinitionsContext = createContext<readonly ModuleDefinition[]>([])

/**
 * Every module definition the app ships (`app/` passes `@/modules`: core never imports modules,
 * modules.md §3). Which of them are active depends on the vault.
 */
export function ModuleDefinitionsProvider({
  definitions,
  children,
}: {
  definitions: readonly ModuleDefinition[]
  children: ReactNode
}) {
  return <DefinitionsContext value={definitions}>{children}</DefinitionsContext>
}

export function useModuleDefinitions(): readonly ModuleDefinition[] {
  return useContext(DefinitionsContext)
}

const NONE: readonly ModuleDefinition[] = []

/**
 * The modules active in a vault (the current route's vault by default), once its registry has
 * loaded: an empty list before, and outside vaults.
 */
export function useActiveModules(vault?: string): {
  modules: readonly ModuleDefinition[]
  isPending: boolean
} {
  const params = useParams({ strict: false })
  const id = vault ?? params.vault
  const definitions = useModuleDefinitions()
  const registry = useRegistry(id ?? '', { enabled: id !== undefined })
  const states = registry.data?.modules
  const modules = useMemo(
    () => (states === undefined ? NONE : activeModules(definitions, states)),
    [definitions, states],
  )
  return { modules, isPending: id !== undefined && registry.isPending }
}

/** A list extension point (navSections, entityPanels, commands, …) of the active modules. */
export function useExtensionList<K extends ListPoint>(point: K, vault?: string) {
  const { modules } = useActiveModules(vault)
  return useMemo(() => collectList(modules, point), [modules, point])
}

/** A keyed extension point (linkTypeRenderers, fieldTypeRenderers, …) of the active modules. */
export function useExtensionRecord<K extends RecordPoint>(point: K, vault?: string) {
  const { modules } = useActiveModules(vault)
  return useMemo(() => collectRecord(modules, point), [modules, point])
}
