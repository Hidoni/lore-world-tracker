import { createRoute, lazyRouteComponent } from '@tanstack/react-router'

import { defineModule, lazyComponent, type EntityViewProps } from '@/core/modules'
import { useKind } from '@/core/registry'

const WorldlinePanel = lazyComponent(
  async () => (await import('./views/worldline-panel')).WorldlinePanel,
)
const JumpArcsLayer = lazyComponent(async () => (await import('./views/jump-arcs')).JumpArcsLayer)

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
      component: WorldlinePanel,
      placement: 'main',
      order: 25,
      useShown: useWorldlineShown,
    },
  ],
  timelineLayers: [{ id: 'worldlines.jumps', title: 'Jumps', component: JumpArcsLayer }],
})
