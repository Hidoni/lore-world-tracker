import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps } from '@/core/modules'

import { LexiconHit } from './editor/lexicon-hit'
import { LexiconRefNode } from './editor/lexicon-ref-view'

/** A panel loaded with the first page that shows it. */
function lazyPanel(
  load: () => Promise<ComponentType<EntityViewProps>>,
): ComponentType<EntityViewProps> {
  const Lazy = lazy(async () => ({ default: await load() }))
  return function Panel(props: EntityViewProps) {
    return createElement(Suspense, { fallback: null }, createElement(Lazy, props))
  }
}

const FamilyPanel = lazyPanel(async () => (await import('./panels/family-panel')).FamilyPanel)
const SpeakersPanel = lazyPanel(async () => (await import('./panels/speakers-panel')).SpeakersPanel)
const ScriptsPanel = lazyPanel(async () => (await import('./panels/scripts-panel')).ScriptsPanel)
const LexiconPanel = lazyPanel(async () => (await import('./panels/lexicon-panel')).LexiconPanel)

/**
 * The languages module (docs/modules/languages.md): languages (dialects as children) and writing
 * systems, with their family, speakers and scripts, a family tree view, and each language's
 * lexicon (panel, full page, entry drawer, CSV import and export; `lexiconRef` words in rich
 * text).
 */
export default defineModule({
  id: 'languages',
  kinds: {
    language: { icon: 'languages', listColumns: ['status', 'code'] },
    writing_system: { icon: 'type', listColumns: ['script_type', 'direction'] },
  },
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: 'family-tree',
      component: lazyRouteComponent(() => import('./views/family-tree-page')),
    }),
    createRoute({
      getParentRoute: () => parent,
      path: '$language/lexicon',
      component: lazyRouteComponent(() => import('./views/lexicon-page')),
    }),
  ],
  entityPanels: [
    {
      id: 'languages.lexicon',
      kinds: ['language'],
      title: 'Lexicon',
      component: LexiconPanel,
      placement: 'main',
      order: 5,
    },
    {
      id: 'languages.family',
      kinds: ['language'],
      title: 'Family',
      component: FamilyPanel,
      placement: 'main',
      order: 10,
    },
    {
      id: 'languages.speakers',
      kinds: ['language'],
      title: 'Speakers',
      component: SpeakersPanel,
      placement: 'side',
      order: 10,
    },
    {
      id: 'languages.scripts',
      kinds: ['language', 'writing_system'],
      title: 'Scripts',
      component: ScriptsPanel,
      placement: 'side',
      order: 11,
    },
  ],
  editorExtensions: [() => import('./editor/lexicon-ref').then((loaded) => loaded.LexiconRef)],
  richTextNodeRenderers: { lexiconRef: LexiconRefNode },
  searchResultRenderers: { 'languages.lexicon_entry': LexiconHit },
  commands: [
    {
      id: 'languages.family-tree',
      title: 'Open the language family tree',
      keywords: ['languages', 'family'],
      run: ({ vault, navigate }) => {
        if (vault !== undefined) navigate(`/v/${vault}/m/languages/family-tree`)
      },
    },
  ],
})
