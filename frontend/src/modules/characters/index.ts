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

/**
 * The characters module (docs/modules/characters.md): people with relationships (family, social,
 * other), affiliations from other modules, and the events of their life.
 */
export default defineModule({
  id: 'characters',
  kinds: {
    character: { icon: 'user', listColumns: ['epithet', 'occupation'] },
  },
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
