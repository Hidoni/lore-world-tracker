import { defineModule, lazyComponent, type EntityViewProps } from '@/core/modules'
import { useBranching } from '@/core/time'

const TimelinePanel = lazyComponent(
  async () => (await import('./views/timeline-panel')).TimelinePanel,
)
const NotesPanel = lazyComponent(
  async () => (await import('./views/notes-panel')).TimelineNotesPanel,
)

/** The notes panel shows while a branch is viewed. */
function useNotesShown({ vault }: EntityViewProps): boolean {
  const branching = useBranching(vault)
  return branching.enabled && branching.inBranch
}

/**
 * The branches module (docs/modules/branches.md): "what if" timelines. Branching itself is core
 * (the timeline switcher, badges on inherited records, overrides, compare mode); this module adds
 * the timeline page (lineage, branch point, what a branch changed, its branches) and the notes an
 * entity has in the viewed branch, and marks branching as available.
 */
export default defineModule({
  id: 'branches',
  entityPanels: [
    {
      id: 'branches.timeline',
      kinds: ['timeline'],
      title: 'Timeline',
      component: TimelinePanel,
      placement: 'main',
      order: 10,
    },
    {
      id: 'branches.notes',
      kinds: '*',
      title: 'Notes in this timeline',
      component: NotesPanel,
      placement: 'main',
      order: 20,
      useShown: useNotesShown,
    },
  ],
})
