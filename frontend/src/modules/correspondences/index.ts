import { defineModule, lazyComponent } from '@/core/modules'

import { useConcurrentlyShown } from './concurrently'

const CorrespondencesSection = lazyComponent(
  async () => (await import('./views/dimension-section')).CorrespondencesSection,
)
const ConcurrentlyPanel = lazyComponent(
  async () => (await import('./views/concurrently-panel')).ConcurrentlyPanel,
)

/**
 * The correspondences module (docs/modules/correspondences.md): how the times of dimensions
 * relate. Mapping itself is core (the timeline's dimension lanes, `@/core/time` correspondence
 * graphs); this module adds the editor and the connected dimensions to the dimension overview, and
 * "Concurrently in…" to event pages.
 */
export default defineModule({
  id: 'correspondences',
  dimensionSections: [
    { id: 'correspondences', title: 'Correspondences', component: CorrespondencesSection },
  ],
  entityPanels: [
    {
      id: 'correspondences.concurrently',
      kinds: ['event'],
      title: 'Concurrently in…',
      component: ConcurrentlyPanel,
      placement: 'side',
      order: 30,
      useShown: useConcurrentlyShown,
    },
  ],
})
