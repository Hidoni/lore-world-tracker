import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps } from '@/core/modules'

/** A panel loaded with the first page that shows it. */
function lazyPanel(
  load: () => Promise<ComponentType<EntityViewProps>>,
): ComponentType<EntityViewProps> {
  const Lazy = lazy(async () => ({ default: await load() }))
  return function Panel(props: EntityViewProps) {
    return createElement(Suspense, { fallback: null }, createElement(Lazy, props))
  }
}

const MembersPanel = lazyPanel(
  async () => (await import('./panels/members-panel')).SpeciesMembersPanel,
)
const DescentPanel = lazyPanel(async () => (await import('./panels/descent-panel')).DescentPanel)
const NativeToPanel = lazyPanel(async () => (await import('./panels/native-panel')).NativeToPanel)
const SpeciesChip = lazyPanel(async () => (await import('./panels/species-chip')).SpeciesChip)

/**
 * The species module (docs/modules/species.md): peoples and creatures in a subspecies tree, with
 * members, descent, native lands, a descent tree view and a species chip on character pages.
 */
export default defineModule({
  id: 'species',
  kinds: {
    species: { icon: 'dna', listColumns: ['classification', 'sapience'] },
  },
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: 'descent-tree',
      component: lazyRouteComponent(() => import('./views/descent-tree-page')),
    }),
  ],
  entityPanels: [
    {
      id: 'species.members',
      kinds: ['species'],
      title: 'Members',
      component: MembersPanel,
      placement: 'main',
      order: 10,
    },
    {
      id: 'species.descent',
      kinds: ['species'],
      title: 'Descent',
      component: DescentPanel,
      placement: 'main',
      order: 11,
    },
    {
      id: 'species.native',
      kinds: ['species'],
      title: 'Native to',
      component: NativeToPanel,
      placement: 'side',
      order: 10,
    },
  ],
  entityHeaderMedia: { character: SpeciesChip },
  commands: [
    {
      id: 'species.descent-tree',
      title: 'Open the species descent tree',
      keywords: ['species', 'evolution'],
      run: ({ vault, navigate }) => {
        if (vault !== undefined) navigate(`/v/${vault}/m/species/descent-tree`)
      },
    },
  ],
})
