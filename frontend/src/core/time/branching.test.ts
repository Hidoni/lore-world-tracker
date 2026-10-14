import { describe, expect, it } from 'vitest'

import type { TimelineNode } from '@/data'

import { flattenTimelines, lineageOf, recordPlace } from './branching'

function node(
  id: string,
  parent: string | null,
  branchT: bigint | null,
  children: TimelineNode[] = [],
): TimelineNode {
  return {
    id,
    name: id,
    visibility: 'public',
    is_prime: parent === null,
    parent_timeline_id: parent,
    branch_point: null,
    branch_t: branchT,
    time_status: null,
    trashed: false,
    children,
  }
}

// Prime ← Survives (at 200) ← Exile (at 250); Early (at 100) ← Earlier (at 300: capped at 100).
const tree = [
  node('prime', null, null, [
    node('survives', 'prime', 200n, [node('exile', 'survives', 250n)]),
    node('early', 'prime', 100n, [node('earlier', 'early', 300n)]),
  ]),
]

describe('lineage', () => {
  it('lists parents before branches', () => {
    expect(flattenTimelines(tree).map(({ node, depth }) => `${node.id}:${depth}`)).toEqual([
      'prime:0',
      'survives:1',
      'exile:2',
      'early:1',
      'earlier:2',
    ])
  })

  it('takes the smallest branch point on the way up', () => {
    const cutoffs = (id: string) =>
      lineageOf(tree, id).map((entry) => [entry.timeline.id, entry.cutoff])
    expect(cutoffs('prime')).toEqual([['prime', null]])
    expect(cutoffs('exile')).toEqual([
      ['exile', null],
      ['survives', 250n],
      ['prime', 200n],
    ])
    expect(cutoffs('earlier')).toEqual([
      ['earlier', null],
      ['early', 300n],
      ['prime', 100n],
    ])
    expect(lineageOf(tree, 'unknown')).toEqual([])
  })

  it('places records relative to the branch point', () => {
    const exile = lineageOf(tree, 'exile')
    const place = (
      timelineId: string,
      start: bigint | null,
      end: bigint | null,
      overridesId?: string,
    ) => recordPlace(exile, { timelineId, start, end, overridesId })?.kind ?? null
    expect(place('exile', 260n, null)).toBe('own')
    expect(place('exile', 100n, 300n, 'root')).toBe('override')
    // Inherited from the prime (cut-off 200): over by then, or still going.
    expect(place('prime', 100n, 150n)).toBe('past')
    expect(place('prime', 100n, 200n)).toBe('past') // ends exactly at the branch point
    expect(place('prime', 100n, 300n)).toBe('spanning')
    expect(place('prime', null, null)).toBe('spanning')
    // From the parent branch (cut-off 250).
    expect(place('survives', 210n, 240n)).toBe('past')
    expect(place('survives', 210n, null)).toBe('spanning')
    // Elsewhere, or viewing a prime timeline: no place.
    expect(place('early', 0n, 10n)).toBeNull()
    expect(
      recordPlace(lineageOf(tree, 'prime'), { timelineId: 'prime', start: 0n, end: null }),
    ).toBeNull()
  })
})
