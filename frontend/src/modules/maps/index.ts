import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps } from '@/core/modules'

import { usePinned } from './panels/pinned-panel'

/** A panel loaded with the first page that shows it (with Leaflet: frontend.md §12). */
function lazyPanel(
  load: () => Promise<ComponentType<EntityViewProps>>,
): ComponentType<EntityViewProps> {
  const Lazy = lazy(async () => ({ default: await load() }))
  return function Panel(props: EntityViewProps) {
    return createElement(Suspense, { fallback: null }, createElement(Lazy, props))
  }
}

const MapPanel = lazyPanel(async () => (await import('./panels/map-panel')).MapPanel)
const PinnedPanel = lazyPanel(async () => (await import('./panels/pinned-panel')).PinnedPanel)

/**
 * The maps module (docs/modules/maps.md): location maps drawn with Leaflet, pins filtered by the
 * time cursor, drill-down into nested maps, and "Show on map" on pinned entities.
 */
export default defineModule({
  id: 'maps',
  dependsOn: ['media'],
  routes: (parent) =>
    ['maps/$map', 'maps/$map/pins/$pin'].map((path) =>
      createRoute({
        getParentRoute: () => parent,
        path,
        component: lazyRouteComponent(() => import('./views/map-page')),
      }),
    ),
  entityPanels: [
    {
      id: 'maps.map',
      kinds: ['location'],
      title: 'Map',
      component: MapPanel,
      placement: 'main',
      order: 5,
    },
    {
      id: 'maps.pinned',
      kinds: '*',
      title: 'Show on map',
      component: PinnedPanel,
      placement: 'side',
      order: 20,
      useShown: usePinned,
    },
  ],
})
