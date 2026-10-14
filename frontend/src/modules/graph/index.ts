import { createRoute, lazyRouteComponent } from '@tanstack/react-router'

import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps } from '@/core/modules'

const LazyPanel = lazy(async () => ({
  default: (await import('./views/local-graph-panel')).LocalGraphPanel,
}))

/** The local graph panel, loaded with the first entity page (the renderer loads when drawn). */
const LocalGraphPanel: ComponentType<EntityViewProps> = (props) =>
  createElement(Suspense, { fallback: null }, createElement(LazyPanel, props))

/**
 * The graph module (docs/modules/graph.md): every entity and how they link, explorable and
 * filterable, at the time cursor.
 */
export default defineModule({
  id: 'graph',
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: '/',
      component: lazyRouteComponent(() => import('./views/graph-page')),
    }),
    // The neighborhood of an entity first (from its local graph panel).
    createRoute({
      getParentRoute: () => parent,
      path: 'focus/$entity',
      component: lazyRouteComponent(() => import('./views/graph-page')),
    }),
  ],
  entityPanels: [
    {
      id: 'graph.local',
      kinds: '*',
      title: 'Local graph',
      component: LocalGraphPanel,
      placement: 'side',
      order: 90,
    },
  ],
  commands: [
    {
      id: 'graph.open',
      title: 'Open the graph',
      keywords: ['graph', 'network', 'links', 'map'],
      run: ({ vault, navigate }) => {
        if (vault !== undefined) navigate(`/v/${vault}/m/graph`)
      },
    },
  ],
})
