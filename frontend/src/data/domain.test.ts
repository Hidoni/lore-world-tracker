import { describe, expect, expectTypeOf, it } from 'vitest'

import type { components } from '@/api'
import type { MomentString } from '@/api/moment'

import {
  entityToDomain,
  momentString,
  parseDomain,
  stringifyDomain,
  toDomain,
  toDomainAs,
  toWire,
  type Domain,
} from './domain'

const HUGE = '123456789012345678901234567890123456789'

describe('toDomain', () => {
  it('turns the moments of a timeline window into bigints, nested and nullable', () => {
    const window = {
      items: [
        { entity_id: 'e1', name: 'Founding', start_t: HUGE, end_t: null, importance: 3 },
        { entity_id: 'e2', name: 'Fall', start_t: '0', end_t: '42', importance: 1 },
      ],
      buckets: [{ from: '0', to: '1000', count: 7 }],
      series_bands: [],
      total: 9,
    }
    const domain = toDomain(window, 'TimelineWindow')
    expect(domain.items.map((item) => [item.start_t, item.end_t])).toEqual([
      [BigInt(HUGE), null],
      [0n, 42n],
    ])
    expect(domain.buckets[0]).toMatchObject({ from: 0n, to: 1000n, count: 7 })
    expect(domain.total).toBe(9)
    expect(window.items[0]?.start_t).toBe(HUGE) // the input is untouched
  })

  it('follows schema references and leaves other strings alone', () => {
    const resolved = toDomain(
      {
        items: [
          {
            start: { t: '10', extent: { lo: '10', hi: '11' }, precision: 'base' },
            end: null,
            status: 'ok',
          },
        ],
      },
      'ResolveOut',
    )
    expect(resolved.items[0]?.start).toMatchObject({
      t: 10n,
      extent: { lo: 10n, hi: 11n },
      precision: 'base',
    })
  })

  it('returns schemas without moments unchanged', () => {
    const vault = { id: 'v1', name: '1234' }
    expect(toDomain(vault, 'Vault')).toBe(vault)
  })

  it('applies a shape given inline', () => {
    expect(toDomainAs<{ t: MomentString[] }>({ t: ['1', '2'] }, { o: { t: { a: 'm' } } })).toEqual({
      t: [1n, 2n],
    })
  })

  it('types moments as bigint', () => {
    type Window = Domain<components['schemas']['TimelineWindow']>
    expectTypeOf<Window['items'][number]['start_t']>().toEqualTypeOf<bigint | null>()
    expectTypeOf<Domain<components['schemas']['Vault']>['name']>().toEqualTypeOf<string>()
  })
})

describe('entityToDomain', () => {
  it('converts the moments of an event’s ext, not its time specs', () => {
    const start = { anchor: { kind: 'absolute', t: '5' }, precision: 'base' }
    const event = entityToDomain({
      kind: 'event',
      ext: { start, start_t: '5', end_t: HUGE, series_start_t: null, original_start_t: '5' },
    })
    expect(event.ext).toEqual({
      start, // a spec stays JSON
      start_t: 5n,
      end_t: BigInt(HUGE),
      series_start_t: null,
      original_start_t: 5n,
    })
    const dimension = entityToDomain({
      kind: 'dimension',
      ext: { duration: '100', base_unit: 's' },
    })
    expect(dimension.ext).toEqual({ duration: 100n, base_unit: 's' })
    const character = { kind: 'character', ext: { start_t: '5' } }
    expect(entityToDomain(character)).toBe(character)
    expect(entityToDomain({ kind: 'event', ext: null }).ext).toBeNull()
  })
})

describe('wire and JSON helpers', () => {
  it('turn moments back into strings', () => {
    expect(momentString(BigInt(HUGE))).toBe(HUGE)
    expect(() => momentString(-1n)).toThrow(RangeError)
    expect(toWire({ moments: [1n, 2n], calendar_id: 'c', nested: { t: 0n } })).toEqual({
      moments: ['1', '2'],
      calendar_id: 'c',
      nested: { t: '0' },
    })
  })

  it('round-trip bigints through JSON', () => {
    const value = { at: BigInt(HUGE), list: [0n, 'x', 3], plain: { $bigint: 'kept', other: 1 } }
    const text = stringifyDomain(value)
    expect(text).toContain(`{"$bigint":"${HUGE}"}`)
    expect(parseDomain(text)).toEqual(value)
    expect(() => JSON.stringify(value)).toThrow(TypeError)
  })
})
