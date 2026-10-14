import { validateCorrespondence } from '@lore/chronology'
import { viewport } from '@lore/chronology/viewport'
import { describe, expect, it } from 'vitest'

import { mappedRange, mapItems } from './dimension-lanes'
import type { WindowItem } from './use-timeline-window'

// One unit here is ten there, from 100 ↔ 0 to 200 ↔ 1000.
const c = validateCorrespondence([
  [100n, 0n],
  [200n, 1000n],
])
const toOther = (t: bigint) => c.mapAB(t, 10_000n)
const toHere = (t: bigint) => c.mapBA(t, 10_000n)

function item(start: bigint, end: bigint): WindowItem {
  return {
    entity_id: `e${start}`,
    row_id: `r${start}`,
    name: `Event ${start}`,
    visibility: 'public',
    parent_id: null,
    has_children: false,
    start_t: start,
    end_t: end,
    start_precision: 'base',
    start_approximate: false,
    end_kind: 'time_point',
    end_precision: 'base',
    end_approximate: false,
    importance: 3,
    category: null,
    time_status: 'ok',
    occurrence_key: null,
    series_id: null,
    occurrence_state: null,
  }
}

describe('dimension lanes', () => {
  it('finds what the other dimension shows of the view, even partly undefined', () => {
    expect(mappedRange(viewport(120n, 50n, 500), toOther)).toEqual([200n, 700n])
    // Half the view lies before the sync points: the defined half still counts.
    expect(mappedRange(viewport(0n, 200n, 500), toOther)).toEqual([0n, 1000n])
    expect(mappedRange(viewport(300n, 50n, 500), toOther)).toBeNull()
  })

  it('places the other dimension’s items on this axis (warped)', () => {
    const mapped = mapItems([item(0n, 500n), item(900n, 5000n), item(2000n, 3000n)], toHere)
    expect(mapped.map((each) => [each.start_t, each.end_t])).toEqual([
      [100n, 150n],
      // The end has no corresponding moment: an instant at the start.
      [190n, 190n],
    ])
  })
})
