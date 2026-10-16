import { createRoute, lazyRouteComponent } from '@tanstack/react-router'

import { defineModule, lazyComponent } from '@/core/modules'

import { TYPE_ICONS } from './types'

const ContentsPanel = lazyComponent(
  async () => (await import('./panels/contents-panel')).ContentsPanel,
)
const EventsHerePanel = lazyComponent(
  async () => (await import('./panels/events-panel')).EventsHerePanel,
)
const ResidentsPanel = lazyComponent(
  async () => (await import('./panels/residents-panel')).ResidentsPanel,
)
const ConnectionsPanel = lazyComponent(
  async () => (await import('./panels/connections-panel')).ConnectionsPanel,
)
const EventSitePanel = lazyComponent(
  async () => (await import('./panels/event-site-panel')).EventSitePanel,
)

/**
 * The locations module (docs/modules/locations.md): places nested in a containment tree, with
 * type icons, their contents, events, residents and connections, a tree view, and the event
 * page's "Location" field.
 */
export default defineModule({
  id: 'locations',
  kinds: {
    location: {
      icon: 'map-pin',
      listColumns: ['location_type', 'population'],
      iconBy: { field: 'location_type', icons: TYPE_ICONS },
    },
  },
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: 'tree',
      component: lazyRouteComponent(() => import('./views/tree-page')),
    }),
  ],
  entityPanels: [
    {
      id: 'locations.contents',
      kinds: ['location'],
      title: 'Contents',
      component: ContentsPanel,
      placement: 'main',
      order: 10,
    },
    {
      id: 'locations.events',
      kinds: ['location'],
      title: 'Events here',
      component: EventsHerePanel,
      placement: 'main',
      order: 11,
    },
    {
      id: 'locations.residents',
      kinds: ['location'],
      title: 'Residents',
      component: ResidentsPanel,
      placement: 'side',
      order: 10,
    },
    {
      id: 'locations.connections',
      kinds: ['location'],
      title: 'Connections',
      component: ConnectionsPanel,
      placement: 'side',
      order: 11,
    },
    {
      id: 'locations.site',
      kinds: ['event'],
      title: 'Location',
      component: EventSitePanel,
      placement: 'side',
      order: -10,
    },
  ],
  commands: [
    {
      id: 'locations.tree',
      title: 'Open the location tree',
      keywords: ['places', 'locations'],
      run: ({ vault, navigate }) => {
        if (vault !== undefined) navigate(`/v/${vault}/m/locations/tree`)
      },
    },
  ],
})
