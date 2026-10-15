import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps, type TimelineLayerProps } from '@/core/modules'
import { useKind } from '@/core/registry'

const LazyPanel = lazy(async () => ({
  default: (await import('./views/worldline-panel')).WorldlinePanel,
}))
const LazyArcs = lazy(async () => ({
  default: (await import('./views/jump-arcs')).JumpArcsLayer,
}))

const lazyView =
  <P extends object>(View: ComponentType<P>): ComponentType<P> =>
  (props) =>
    createElement(Suspense, { fallback: null }, createElement(View, props))

/** The panel shows on kinds that can have a worldline (characters, by default). */
function useWorldlineShown({ vault, kind }: EntityViewProps): boolean {
  return useKind(kind, vault)?.capabilities.can_have_worldline === true
}

/**
 * The worldlines module (docs/modules/worldlines.md): personal timelines. A worldline panel on the
 * kinds that can have one (segments, time travel), the personal timeline view, and a timeline
 * layer with the jumps of chosen entities. Subjective ages (characters' life panel) and the
 * choice of visit for participants are core, reading the module's endpoints when it is on.
 */
export default defineModule({
  id: 'worldlines',
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: 'entities/$entity',
      component: lazyRouteComponent(() => import('./views/personal-timeline-page')),
    }),
  ],
  entityPanels: [
    {
      id: 'worldlines.worldline',
      kinds: '*',
      title: 'Worldline',
      component: lazyView<EntityViewProps>(LazyPanel),
      placement: 'main',
      order: 25,
      useShown: useWorldlineShown,
    },
  ],
  timelineLayers: [
    { id: 'worldlines.jumps', title: 'Jumps', component: lazyView<TimelineLayerProps>(LazyArcs) },
  ],
})
