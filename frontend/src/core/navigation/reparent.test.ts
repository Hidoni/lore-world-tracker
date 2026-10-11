import { describe, expect, it } from 'vitest'

import { buildKindRegistry } from '@/core/registry'
import { kind } from '@/test/fake-vault'
import { makeRegistry } from '@/test/msw'

import { canReparent, childKinds, type TreeEntity } from './reparent'

const registry = buildKindRegistry(
  makeRegistry([], [], {
    kinds: [
      kind('dimension', 'Dimension', { capabilities: { is_system: true } }),
      kind('misc', 'Misc', { allowed_parents: ['misc'] }),
      kind('location', 'Location', { allowed_parents: ['location', 'misc'] }),
      kind('character', 'Character', { allowed_parents: ['misc'] }),
    ] as never,
  }),
  [],
)

const entity = (id: string, kindKey: string, extra: Partial<TreeEntity> = {}): TreeEntity => ({
  id,
  name: id,
  kind: kindKey,
  dimension_id: 'd1',
  parent_id: null,
  ...extra,
})

describe('canReparent', () => {
  const city = entity('city', 'location', { parent_id: 'region' })
  const region = entity('region', 'location')

  it('allows the kinds a kind may be inside', () => {
    expect(canReparent(registry, city, entity('folder', 'misc'))).toEqual({ ok: true })
    expect(canReparent(registry, region, entity('world', 'location'))).toEqual({ ok: true })
  })

  it('rejects other kinds, cycles, itself and the current parent', () => {
    expect(canReparent(registry, city, entity('hero', 'character'))).toEqual({
      ok: false,
      reason: 'A location can’t be inside a character',
    })
    expect(canReparent(registry, region, city, ['region'])).toEqual({
      ok: false,
      reason: 'city is inside region',
    })
    expect(canReparent(registry, city, city).ok).toBe(false)
    expect(canReparent(registry, city, region)).toEqual({ ok: false, reason: 'Already in region' })
  })

  it('keeps entities in their dimension unless one side is multiversal', () => {
    const elsewhere = entity('elsewhere', 'misc', { dimension_id: 'd2' })
    expect(canReparent(registry, city, elsewhere)).toEqual({
      ok: false,
      reason: 'elsewhere is in another dimension',
    })
    expect(canReparent(registry, city, { ...elsewhere, dimension_id: null }).ok).toBe(true)
    expect(canReparent(registry, { ...city, dimension_id: null }, elsewhere).ok).toBe(true)
  })

  it('moves to the top unless already there', () => {
    expect(canReparent(registry, city, null)).toEqual({ ok: true })
    expect(canReparent(registry, region, null).ok).toBe(false)
  })
})

describe('childKinds', () => {
  it('lists the non-system kinds allowed inside a kind', () => {
    expect(childKinds(registry, 'misc').map((k) => k.key)).toEqual([
      'misc',
      'location',
      'character',
    ])
    expect(childKinds(registry, 'location').map((k) => k.key)).toEqual(['location'])
    expect(childKinds(registry, 'dimension')).toEqual([])
  })
})
