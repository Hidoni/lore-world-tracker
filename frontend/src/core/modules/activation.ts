import type { ModuleDefinition } from './types'

interface ModuleState {
  id: string
  enabled: boolean
}

/**
 * The definitions active in a vault: the module is enabled in `GET /registry` and so is every
 * module it depends on (modules.md §4). Order follows `definitions`.
 */
export function activeModules(
  definitions: readonly ModuleDefinition[],
  states: readonly ModuleState[],
): ModuleDefinition[] {
  const enabled = new Set(states.filter((state) => state.enabled).map((state) => state.id))
  return definitions.filter(
    (definition) =>
      enabled.has(definition.id) && (definition.dependsOn ?? []).every((id) => enabled.has(id)),
  )
}

type ListPoint = {
  [K in keyof ModuleDefinition]-?: NonNullable<ModuleDefinition[K]> extends readonly unknown[]
    ? K
    : never
}[keyof ModuleDefinition]

type RecordPoint = Exclude<
  {
    [K in keyof ModuleDefinition]-?: NonNullable<ModuleDefinition[K]> extends Readonly<
      Record<string, unknown>
    >
      ? NonNullable<ModuleDefinition[K]> extends readonly unknown[]
        ? never
        : K
      : never
  }[keyof ModuleDefinition],
  'graphStyles'
>

type Item<K extends ListPoint> = NonNullable<ModuleDefinition[K]>[number]
type Entry<K extends RecordPoint> = NonNullable<ModuleDefinition[K]>[string]

/** A list extension point of the active modules, in module order (then `order`, if any). */
export function collectList<K extends ListPoint>(
  modules: readonly ModuleDefinition[],
  point: K,
): Item<K>[] {
  const items = modules.flatMap((module) => [...((module[point] ?? []) as readonly Item<K>[])])
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => order(a.item) - order(b.item) || a.index - b.index)
    .map(({ item }) => item)
}

function order(item: unknown): number {
  const value = (item as { order?: unknown }).order
  return typeof value === 'number' ? value : 0
}

/** A keyed extension point of the active modules (a later module wins a key). */
export function collectRecord<K extends RecordPoint>(
  modules: readonly ModuleDefinition[],
  point: K,
): Record<string, Entry<K>> {
  const merged: Record<string, Entry<K>> = {}
  for (const module of modules) Object.assign(merged, module[point] ?? {})
  return merged
}

export type { ListPoint, RecordPoint }
