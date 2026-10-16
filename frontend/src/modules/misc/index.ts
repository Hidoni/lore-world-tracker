import { defineModule, lazyComponent } from '@/core/modules'

// Loaded with the first misc page: the module costs nothing until then.
const ChildrenPanel = lazyComponent(
  async () => (await import('./panels/children-panel')).ChildrenPanel,
)

/**
 * The misc module (docs/modules/misc.md): entries that don't fit elsewhere and hold children of
 * every kind. The sidebar groups them by category; their page lists their children by kind.
 */
export default defineModule({
  id: 'misc',
  kinds: {
    misc: { icon: 'shapes', listColumns: ['category'], groupBy: 'category' },
  },
  entityPanels: [
    {
      id: 'misc.children',
      kinds: ['misc'],
      title: 'Children',
      component: ChildrenPanel,
      placement: 'main',
    },
  ],
})
