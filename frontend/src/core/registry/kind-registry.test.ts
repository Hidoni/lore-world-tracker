import { CircleIcon, GemIcon, OrbitIcon } from 'lucide-react'
import { describe, expect, it } from 'vitest'

import { makeRegistry } from '@/test/msw'
import { fixtureModule } from '@/test/fixture-module'

import { iconFor } from './icons'
import { buildKindRegistry } from './kind-registry'

const CAPS = {
  has_body: true,
  can_be_multiversal: false,
  has_existence: true,
  can_have_worldline: false,
  is_time_bound: false,
  is_system: false,
}

function kind(key: string, icon: string, module = 'core') {
  return {
    key,
    module,
    label: key,
    plural: `${key}s`,
    icon,
    color: '#000000',
    description: '',
    allowed_parents: ['misc'],
    capabilities: CAPS,
    fields: [],
  }
}

const REGISTRY = makeRegistry(['fixture'], [], {
  kinds: [kind('dimension', 'orbit'), kind('relic', 'box', 'fixture'), kind('odd', 'no-such-icon')],
})

describe('buildKindRegistry', () => {
  it('uses the server’s kinds, icons and colors without modules', () => {
    const registry = buildKindRegistry(REGISTRY, [])
    expect(registry.kinds.map((k) => k.key)).toEqual(['dimension', 'relic', 'odd'])
    expect(registry.kind('dimension')).toMatchObject({
      icon: OrbitIcon,
      color: '#000000',
      panels: [],
    })
    expect(registry.kind('odd')?.icon).toBe(CircleIcon) // unknown icon names fall back
    expect(registry.kind('relic')?.headerMedia).toEqual([])
  })

  it('merges active modules’ UI configs, panels and renderers', () => {
    const linkType = {
      key: 'fixture.guards',
      module: 'fixture',
      user_defined: false,
      label: 'guards',
      inverse_label: null,
      description: '',
      source_kinds: '*',
      target_kinds: '*',
      symmetric: false,
    } as unknown as (typeof REGISTRY.link_types)[number]
    const registry = buildKindRegistry({ ...REGISTRY, link_types: [linkType] }, [fixtureModule])
    const relic = registry.kind('relic')
    expect(relic).toMatchObject({
      iconName: 'gem',
      icon: GemIcon,
      color: '#123456',
      listColumns: ['age'],
      createDefaults: { age: 1 },
    })
    expect(relic?.panels.map((panel) => panel.id)).toEqual(['fixture.first', 'fixture.later'])
    expect(relic?.headerMedia).toHaveLength(1)
    expect(registry.kind('dimension')?.panels.map((panel) => panel.id)).toEqual(['fixture.first'])
    expect(registry.linkType('fixture.guards')?.renderer).not.toBeNull()
    expect(registry.kind('nope')).toBeUndefined()
    expect(iconFor('gem')).toBe(GemIcon)
  })
})
