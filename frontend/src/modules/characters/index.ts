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

const RelationshipsPanel = lazyPanel(
  async () => (await import('./panels/relationships-panel')).RelationshipsPanel,
)
const AffiliationsPanel = lazyPanel(
  async () => (await import('./panels/affiliations-panel')).AffiliationsPanel,
)
const LifePanel = lazyPanel(async () => (await import('./panels/life-panel')).LifePanel)
const FamilyTreePanel = lazyPanel(
  async () => (await import('./panels/family-tree-panel')).FamilyTreePanel,
)

/**
 * The characters module (docs/modules/characters.md): people with relationships (family, social,
 * other), affiliations from other modules, the events of their life, and their family tree
 * (panel and view).
 */
export default defineModule({
  id: 'characters',
  kinds: {
    character: { icon: 'user', listColumns: ['epithet', 'occupation'] },
  },
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: '$character/family-tree',
      component: lazyRouteComponent(() => import('./views/family-tree-page')),
    }),
  ],
  entityPanels: [
    {
      id: 'characters.relationships',
      kinds: ['character'],
      title: 'Relationships',
      component: RelationshipsPanel,
      placement: 'main',
      order: 10,
    },
    {
      id: 'characters.family-tree',
      kinds: ['character'],
      title: 'Family tree',
      component: FamilyTreePanel,
      placement: 'main',
      order: 12,
    },
    {
      id: 'characters.life',
      kinds: ['character'],
      title: 'Life',
      component: LifePanel,
      placement: 'main',
      order: 11,
    },
    {
      id: 'characters.affiliations',
      kinds: ['character'],
      title: 'Affiliations',
      component: AffiliationsPanel,
      placement: 'side',
      order: 10,
    },
  ],
})
