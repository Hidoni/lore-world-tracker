import { createRoute, lazyRouteComponent } from '@tanstack/react-router'

import { defineModule } from '@/core/modules'

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
