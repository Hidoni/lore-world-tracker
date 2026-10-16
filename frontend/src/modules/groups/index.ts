import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import type { ComponentType } from 'react'

import { defineModule, lazyComponent, type EntityViewProps } from '@/core/modules'

const MembersPanel = lazyComponent(async () => (await import('./panels/members-panel')).MembersPanel)
const LeadershipPanel = lazyComponent(
  async () => (await import('./panels/leadership-panel')).LeadershipPanel,
)
const StructurePanel = lazyComponent(
  async () => (await import('./panels/structure-panel')).StructurePanel,
)
const RelationsPanel = lazyComponent(
  async () => (await import('./panels/relations-panel')).GroupRelationsPanel,
)
const TerritoryPanel = lazyComponent(
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
 * their ranks (and their history as a Gantt chart), the leadership succession, structure (and an
 * org chart view), relations with other groups and territory.
 */
export default defineModule({
  id: 'groups',
  kinds: {
    group: { icon: 'users', listColumns: ['group_type', 'motto'] },
  },
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: '$group/org-chart',
      component: lazyRouteComponent(() => import('./views/org-chart-page')),
    }),
  ],
  entityPanels: [
    panel('members', 'Members', MembersPanel, 'main', 10),
    panel('structure', 'Structure', StructurePanel, 'main', 11),
    panel('leadership', 'Leadership', LeadershipPanel, 'side', 10),
    panel('relations', 'Group relations', RelationsPanel, 'side', 11),
    panel('territory', 'Territory', TerritoryPanel, 'side', 12),
  ],
})
