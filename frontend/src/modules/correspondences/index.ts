import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule } from '@/core/modules'

import { useConcurrentlyShown } from './concurrently'

const LazySection = lazy(async () => ({
  default: (await import('./views/dimension-section')).CorrespondencesSection,
}))
const LazyConcurrently = lazy(async () => ({
  default: (await import('./views/concurrently-panel')).ConcurrentlyPanel,
}))

const lazyView =
  <P extends object>(View: ComponentType<P>): ComponentType<P> =>
  (props) =>
    createElement(Suspense, { fallback: null }, createElement(View, props))

/**
 * The correspondences module (docs/modules/correspondences.md): how the times of dimensions
 * relate. Mapping itself is core (the timeline's dimension lanes, `@/core/time` correspondence
 * graphs); this module adds the editor and the connected dimensions to the dimension overview, and
 * "Concurrently in…" to event pages.
 */
export default defineModule({
  id: 'correspondences',
  dimensionSections: [
    { id: 'correspondences', title: 'Correspondences', component: lazyView(LazySection) },
  ],
  entityPanels: [
    {
      id: 'correspondences.concurrently',
      kinds: ['event'],
      title: 'Concurrently in…',
      component: lazyView(LazyConcurrently),
      placement: 'side',
      order: 30,
      useShown: useConcurrentlyShown,
    },
  ],
})
