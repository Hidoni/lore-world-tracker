import { describe, expect, it } from 'vitest'

import type { CorrespondenceOut } from '@/data'

import {
  compileStored,
  correspondenceGraph,
  mapper,
  reachableFrom,
  shortestPath,
} from './correspondences'

function row(
  id: string,
  a: string,
  b: string,
  points: readonly (readonly [bigint | null, bigint | null])[],
  extra: Partial<CorrespondenceOut> = {},
): CorrespondenceOut {
  return {
    id,
    dimension_a_id: a,
    dimension_b_id: b,
    name: id,
    extrapolation: 'none',
    rate_before: null,
    rate_after: null,
    note: null,
    visibility: 'public',
    revision: 1,
    created_at: '',
    updated_at: '',
    deleted_at: null,
    points: points.map(([at, bt], index) => ({
      id: `${id}-${index}`,
      a: null,
      b: null,
      a_t: at,
      b_t: bt,
      time_status: 'ok',
      note: null,
    })),
    ...extra,
  }
}

const D = new Map([
  ['aetheria', 10_000n],
  ['dream', 10_000n],
  ['under', 10_000n],
  ['lost', 10_000n],
])

describe('correspondence graphs (the server twin: lore.core.time.correspondences)', () => {
  it('interpolates, floors back and stops at the sync points', () => {
    const graph = correspondenceGraph(
      [
        row('c1', 'aetheria', 'dream', [
          [100n, 1000n],
          [200n, 3000n],
        ]),
      ],
      D,
    )
    const there = mapper(graph, 'aetheria', 'dream')
    const back = mapper(graph, 'dream', 'aetheria')
    expect(there?.(150n)).toBe(2000n)
    expect(back?.(2010n)).toBe(150n)
    expect(there?.(50n)).toBeNull()
    expect(there?.(-1n)).toBeNull()
    expect(mapper(graph, 'aetheria', 'aetheria')?.(7n)).toBe(7n)
    expect(mapper(graph, 'aetheria', 'under')).toBeNull()
  })

  it('composes along the shortest path, ties to the smallest ids', () => {
    const graph = correspondenceGraph(
      [
        row('c1', 'aetheria', 'dream', [
          [100n, 1000n],
          [200n, 2000n],
        ]),
        row('c2', 'under', 'dream', [
          [10n, 1000n],
          [20n, 3000n],
        ]),
      ],
      D,
    )
    // 150 → 1500 in the Dreamrealm → 12 in the Underworld.
    expect(mapper(graph, 'aetheria', 'under')?.(150n)).toBe(12n)
    expect(shortestPath(graph, 'aetheria', 'under')?.map((edge) => edge.correspondenceId)).toEqual([
      'c1',
      'c2',
    ])
    expect(reachableFrom(graph, 'aetheria')).toEqual(['dream', 'under'])
    const direct = correspondenceGraph(
      [
        row('c1', 'aetheria', 'dream', [
          [100n, 1000n],
          [200n, 2000n],
        ]),
        row('c2', 'under', 'dream', [
          [10n, 1000n],
          [20n, 3000n],
        ]),
        row('c3', 'aetheria', 'under', [
          [100n, 10n],
          [200n, 40n],
        ]),
      ],
      D,
    )
    expect(shortestPath(direct, 'aetheria', 'under')?.map((edge) => edge.correspondenceId)).toEqual(
      ['c3'],
    )
  })

  it('extrapolates with rates and leaves out what it can’t compile', () => {
    const rate = { num: '365', den: '1' }
    const graph = correspondenceGraph(
      [
        row('c1', 'aetheria', 'dream', [[100n, 0n]], {
          extrapolation: 'rate',
          rate_before: rate,
          rate_after: rate,
        }),
        row('c2', 'aetheria', 'lost', [[100n, null]]),
        row('c3', 'aetheria', 'under', [[100n, 10n]], { deleted_at: '2026-10-14' }),
      ],
      D,
    )
    expect(mapper(graph, 'aetheria', 'dream')?.(10n + 100n)).toBe(3650n)
    expect(mapper(graph, 'aetheria', 'dream')?.(99n)).toBeNull()
    expect(reachableFrom(graph, 'aetheria')).toEqual(['dream'])
    expect(
      compileStored(
        row('bad', 'a', 'b', [
          [1n, 5n],
          [2n, 3n],
        ]),
      ),
    ).toBeNull()
  })
})
