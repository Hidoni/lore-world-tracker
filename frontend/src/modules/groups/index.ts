import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps } from '@/core/modules'

/** A panel loaded with the first page that shows it. */
function lazyPanel(
  load: () => Promise<ComponentType<EntityViewProps>>,
): ComponentType<EntityViewProps> {
  const Lazy = lazy(async () => ({ default: await load() }))
  return function Panel(props: EntityViewProps) {
    return createElement(Suspense, { fallback: null }, createElement(Lazy, props))
  }
}

const MembersPanel = lazyPanel(async () => (await import('./panels/members-panel')).MembersPanel)
const LeadershipPanel = lazyPanel(
  async () => (await import('./panels/leadership-panel')).LeadershipPanel,
)
const StructurePanel = lazyPanel(
  async () => (await import('./panels/structure-panel')).StructurePanel,
)
const RelationsPanel = lazyPanel(
  async () => (await import('./panels/relations-panel')).GroupRelationsPanel,
)
const TerritoryPanel = lazyPanel(
  async () => (await import('./panels/territory-panel')).TerritoryPanel,
)

const panel = (
  id: string,
  title: string,
  component: ComponentType<EntityViewProps>,
  placement: 'main' | 'side',
  order: number,
) => ({ id: `groups.${id}`, kinds: ['group'], title, component, placement, order })

/**
 * The groups module (docs/modules/groups.md): organizations in a sub-group tree, with members and
 * their ranks, the leadership succession, structure, relations with other groups and territory.
 */
export default defineModule({
  id: 'groups',
  kinds: {
    group: { icon: 'users', listColumns: ['group_type', 'motto'] },
  },
  entityPanels: [
    panel('members', 'Members', MembersPanel, 'main', 10),
    panel('structure', 'Structure', StructurePanel, 'main', 11),
    panel('leadership', 'Leadership', LeadershipPanel, 'side', 10),
    panel('relations', 'Group relations', RelationsPanel, 'side', 11),
    panel('territory', 'Territory', TerritoryPanel, 'side', 12),
  ],
})
