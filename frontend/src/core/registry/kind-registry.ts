import type { LucideIcon } from 'lucide-react'
import type { ComponentType } from 'react'

import type { components } from '@/data'
import { collectList, collectRecord } from '@/core/modules/activation'
import type {
  EntityPanel,
  EntityViewProps,
  LinkRowProps,
  ModuleDefinition,
} from '@/core/modules/types'

import { iconFor } from './icons'

type Schemas = components['schemas']

/** A kind as the UI uses it: the server's definition merged with module UI configs. */
export interface Kind {
  key: string
  module: string
  label: string
  plural: string
  description: string
  iconName: string
  icon: LucideIcon
  color: string
  allowedParents: readonly string[]
  capabilities: Schemas['KindCapabilitiesOut']
  fields: readonly Schemas['FieldOut'][]
  /** Entity panels of active modules for this kind, ordered. */
  panels: readonly EntityPanel[]
  headerMedia: ComponentType<EntityViewProps> | null
  listColumns: readonly string[]
  createDefaults: Readonly<Record<string, unknown>>
  /** The text field the sidebar groups the kind's top level by, if any. */
  groupBy: string | null
}

export interface LinkType extends Readonly<Schemas['LinkTypeOut']> {
  /** A module's row renderer for links of this type, if any. */
  renderer: ComponentType<LinkRowProps> | null
}

export interface KindRegistry {
  kinds: readonly Kind[]
  linkTypes: readonly LinkType[]
  /** Record types whose slots relative anchors may reference (time-model.md §6). */
  referenceableSlots: readonly Schemas['TimeSlotsOut'][]
  kind(key: string): Kind | undefined
  linkType(key: string): LinkType | undefined
}

/**
 * Merges `GET /registry` with the active modules' UI configs (frontend.md §7). The server's
 * icon and color apply unless a module overrides them.
 */
export function buildKindRegistry(
  registry: Schemas['Registry'],
  modules: readonly ModuleDefinition[],
): KindRegistry {
  const panels = collectList(modules, 'entityPanels')
  const headerMedia = collectRecord(modules, 'entityHeaderMedia')
  const renderers = collectRecord(modules, 'linkTypeRenderers')
  const ui = Object.assign({}, ...modules.map((module) => module.kinds ?? {})) as NonNullable<
    ModuleDefinition['kinds']
  >
  const kinds = registry.kinds.map((kind): Kind => {
    const config = ui[kind.key] ?? {}
    const iconName = config.icon ?? kind.icon
    return {
      key: kind.key,
      module: kind.module,
      label: kind.label,
      plural: kind.plural,
      description: kind.description,
      iconName,
      icon: iconFor(iconName),
      color: config.color ?? kind.color,
      allowedParents: kind.allowed_parents,
      capabilities: kind.capabilities,
      fields: kind.fields,
      panels: panels.filter((panel) => panel.kinds === '*' || panel.kinds.includes(kind.key)),
      headerMedia: headerMedia[kind.key] ?? null,
      listColumns: config.listColumns ?? [],
      createDefaults: config.createDefaults ?? {},
      groupBy: config.groupBy ?? null,
    }
  })
  const linkTypes = registry.link_types.map((linkType): LinkType => ({
    ...linkType,
    renderer: renderers[linkType.key] ?? null,
  }))
  const kindsByKey = new Map(kinds.map((kind) => [kind.key, kind]))
  const linkTypesByKey = new Map(linkTypes.map((linkType) => [linkType.key, linkType]))
  return {
    kinds,
    linkTypes,
    referenceableSlots: registry.referenceable_slots,
    kind: (key) => kindsByKey.get(key),
    linkType: (key) => linkTypesByKey.get(key),
  }
}
