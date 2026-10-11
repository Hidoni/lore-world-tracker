import { createRoute, lazyRouteComponent } from '@tanstack/react-router'

import { defineModule, type EntityViewProps } from '@/core/modules'
import { useKind } from '@/core/registry'

let viewLoads = 0

/** How many times the lazy route component was loaded. */
export function fixtureViewLoads(): number {
  return viewLoads
}

/** A nav section that reads the KindRegistry through `useKind`. */
function FixtureSection({ vault }: { vault: string }) {
  const kind = useKind('relic', vault)
  if (kind === undefined) return null
  const Icon = kind.icon
  return (
    <p data-testid="fixture-kind" data-icon={kind.iconName} style={{ color: kind.color }}>
      <Icon aria-hidden /> {kind.plural} ({kind.panels.map((panel) => panel.id).join(',')})
    </p>
  )
}

function Panel(props: EntityViewProps) {
  return <p>{props.entityId}</p>
}

/**
 * A module using every extension point (modules.md §3), for tests. It is not in `@/modules`:
 * tests pass it to `renderApp`.
 */
export const fixtureModule = defineModule({
  id: 'fixture',
  kinds: {
    relic: { icon: 'gem', color: '#123456', listColumns: ['age'], createDefaults: { age: 1 } },
  },
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: 'view',
      component: lazyRouteComponent(async () => {
        viewLoads += 1
        return import('./views/fixture-view')
      }),
    }),
  ],
  navSections: [{ id: 'fixture.relics', title: 'Relics', component: FixtureSection }],
  entityPanels: [
    {
      id: 'fixture.later',
      kinds: ['relic'],
      title: 'Later',
      component: Panel,
      placement: 'side',
      order: 2,
    },
    {
      id: 'fixture.first',
      kinds: '*',
      title: 'First',
      component: Panel,
      placement: 'main',
      order: 1,
    },
    {
      id: 'fixture.events',
      kinds: ['event'],
      title: 'Events',
      component: Panel,
      placement: 'main',
    },
  ],
  linkTypeRenderers: { 'fixture.guards': () => <span>guards</span> },
  fieldTypeRenderers: { 'fixture.rune': () => <span>rune</span> },
  timelineLayers: [{ id: 'fixture.layer', title: 'Relic lane', component: () => null }],
  graphStyles: {
    nodes: { relic: { color: '#123456' } },
    edges: { 'fixture.guards': { dashed: true } },
  },
  editorExtensions: [{ name: 'fixtureMark' }],
  commands: [{ id: 'fixture.polish', title: 'Polish relics', run: () => undefined }],
  settingsPages: [{ id: 'fixture', title: 'Relic settings', component: () => null }],
  searchResultRenderers: { 'fixture.relic': () => <span>relic hit</span> },
  entityHeaderMedia: { relic: Panel },
})

/** A module depending on the fixture one. */
export const dependentModule = defineModule({
  id: 'dependent',
  dependsOn: ['fixture'],
  commands: [{ id: 'dependent.go', title: 'Go', run: () => undefined }],
})
