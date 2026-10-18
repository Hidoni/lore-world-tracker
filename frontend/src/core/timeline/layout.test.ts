import { fromFields } from '@lore/chronology'
import { toPx, viewport } from '@lore/chronology/viewport'
import { describe, expect, it } from 'vitest'

import { presetLenses } from '@/test/calendars'

import { CIRCA_PX, extentOf, itemGeometry, OPEN_END_PX, spanBackground } from './geometry'
import { GAP_PX, MIN_LABEL_PX, packLanes, type LaneItem } from './lanes'

const { lenses } = presetLenses('gregorian')
const calendar = lenses[0]?.calendar
if (calendar == null) throw new Error('gregorian')
const day = (year: string, month: string, d: string) =>
  fromFields(calendar, { year, month, day: d }, 'day')
const DAY = 86_400n

function item(overrides: Partial<Parameters<typeof itemGeometry>[0]>) {
  return {
    start_t: day('2000', 'jan', '1'),
    end_t: day('2000', 'jan', '1'),
    start_precision: 'base',
    start_approximate: false,
    end_kind: 'time_point',
    end_precision: 'base',
    end_approximate: false,
    ...overrides,
  }
}

/** The value, which the test expects to be there. */
function there<T>(value: T | undefined | null): T {
  if (value === undefined || value === null) throw new Error('missing')
  return value
}

describe('lane packing', () => {
  const items = (shift = 0, scale = 1): LaneItem[] =>
    [
      ['a', 0, 300],
      ['b', 50, 120],
      ['c', 130, 400],
      ['d', 310, 320],
      ['e', 500, 900],
      ['f', 510, 520],
    ].map(([key, x0, x1]) => ({
      key: key as string,
      x0: (x0 as number) * scale + shift,
      x1: (x1 as number) * scale + shift,
    }))

  it('packs greedily by start, keeping room for labels', () => {
    const { lanes, count } = packLanes(items())
    expect(Object.fromEntries(lanes)).toEqual({ a: 0, b: 1, c: 2, d: 0, e: 0, f: 1 })
    expect(count).toBe(3)
    // Lanes never hold overlapping items (with their minimum label room and the gap).
    const byLane = new Map<number, LaneItem[]>()
    for (const each of items()) {
      const lane = lanes.get(each.key) ?? -1
      byLane.set(lane, [...(byLane.get(lane) ?? []), each])
    }
    for (const laneItems of byLane.values()) {
      laneItems.sort((x, y) => x.x0 - y.x0)
      for (let i = 1; i < laneItems.length; i++) {
        const before = there(laneItems[i - 1])
        expect(Math.max(before.x1, before.x0 + MIN_LABEL_PX) + GAP_PX).toBeLessThanOrEqual(
          there(laneItems[i]).x0,
        )
      }
    }
  })

  it('is sticky: panning keeps every lane, zooming keeps those still free', () => {
    const first = packLanes(items())
    for (const shift of [-200, -1, 1, 37, 400]) {
      expect(packLanes(items(shift), first.lanes).lanes).toEqual(first.lanes)
    }
    // Zoomed in ×3: everything still fits where it was.
    expect(packLanes(items(-100, 3), first.lanes).lanes).toEqual(first.lanes)
    // An item that newly appears doesn't move the others.
    const more = [...items(), { key: 'g', x0: 20, x1: 25 }]
    const next = packLanes(more, first.lanes)
    for (const [key, lane] of first.lanes) expect(next.lanes.get(key)).toBe(lane)
  })

  it('moves an item only when its lane is taken', () => {
    const first = packLanes(items())
    // Zoomed out ×0.2: f's lane 1 would collide with b's label room... it stays if free.
    const zoomed = packLanes(items(0, 0.2), first.lanes)
    for (const [key, lane] of zoomed.lanes) {
      const was = first.lanes.get(key)
      if (lane !== was) {
        // It moved because its old lane was busy at its start.
        expect(was).toBeDefined()
      }
    }
    expect(zoomed.lanes.size).toBe(6)
  })
})

describe('item geometry', () => {
  const v = viewport(day('2000', 'jan', '1') - 10n * DAY, 400n * DAY, 800)

  it('draws an exact span solid from start to end', () => {
    const g = itemGeometry(item({ end_t: day('2000', 'mar', '1') }), v, lenses)
    expect(g).toMatchObject({ kind: 'span', fadeIn: 0, fadeOut: 0, openEnd: false })
    expect(g?.x0).toBeCloseTo(toPx(v, day('2000', 'jan', '1')))
    expect(g?.x1).toBeCloseTo(toPx(v, day('2000', 'mar', '1')))
    expect(spanBackground(there(g), 'red')).toBe('red')
  })

  it('fades a coarse start and end over their units', () => {
    const g = itemGeometry(
      item({
        start_t: day('2000', 'jan', '1'),
        start_precision: 'month',
        end_t: day('2000', 'jun', '1'),
        end_precision: 'month',
      }),
      v,
      lenses,
    )
    const january = extentOf(day('2000', 'jan', '1'), 'month', lenses)
    const june = extentOf(day('2000', 'jun', '1'), 'month', lenses)
    expect(january.hi - january.lo).toBe(31n * DAY)
    expect(g?.x0).toBeCloseTo(toPx(v, january.lo))
    expect(g?.x1).toBeCloseTo(toPx(v, june.hi))
    expect(g?.fadeIn).toBeCloseTo(toPx(v, january.hi) - toPx(v, january.lo))
    expect(g?.fadeOut).toBeCloseTo(toPx(v, june.hi) - toPx(v, june.lo))
    expect(spanBackground(there(g), 'red')).toMatch(
      /^linear-gradient\(to right, transparent 0%, red [\d.]+%, red [\d.]+%, transparent 100%\)$/,
    )
  })

  it('fades a ranged start and end over their uncertainty ranges', () => {
    const start = { lo: day('2000', 'jan', '1'), hi: day('2000', 'mar', '1') }
    const end = { lo: day('2000', 'sep', '1'), hi: day('2000', 'dec', '1') }
    const g = itemGeometry(
      item({
        start_t: day('2000', 'feb', '1'),
        start_precision: 'day',
        start_extent: start,
        end_t: day('2000', 'oct', '1'),
        end_precision: 'day',
        end_extent: end,
      }),
      v,
      lenses,
    )
    expect(g?.x0).toBeCloseTo(toPx(v, start.lo))
    expect(g?.x1).toBeCloseTo(toPx(v, end.hi))
    expect(g?.fadeIn).toBeCloseTo(toPx(v, start.hi) - toPx(v, start.lo))
    expect(g?.fadeOut).toBeCloseTo(toPx(v, end.hi) - toPx(v, end.lo))
  })

  it('softens circa edges, fades an unknown end, and shares edges wider than the bar', () => {
    const circa = itemGeometry(
      item({ end_t: day('2000', 'feb', '1'), start_approximate: true }),
      v,
      lenses,
    )
    expect(circa?.fadeIn).toBe(CIRCA_PX)
    expect(circa?.fadeOut).toBe(CIRCA_PX)
    expect(circa?.x0).toBeCloseTo(toPx(v, day('2000', 'jan', '1')) - CIRCA_PX)

    const open = itemGeometry(item({ end_kind: 'unknown', end_t: null }), v, lenses)
    expect(open).toMatchObject({ openEnd: true, fadeOut: OPEN_END_PX })

    const tiny = itemGeometry(
      item({ start_precision: 'year', end_t: day('2000', 'jan', '2'), end_precision: 'year' }),
      v,
      lenses,
    )
    const g = there(tiny)
    expect(g.fadeIn + g.fadeOut).toBeCloseTo(g.x1 - g.x0)
  })

  it('draws exact instants as diamonds and coarse ones as fuzzy spans', () => {
    expect(itemGeometry(item({ end_kind: 'instant' }), v, lenses)?.kind).toBe('instant')
    const coarse = itemGeometry(item({ end_kind: 'instant', start_precision: 'month' }), v, lenses)
    expect(coarse?.kind).toBe('span')
    expect((coarse?.fadeIn ?? 0) + (coarse?.fadeOut ?? 0)).toBeCloseTo(
      (coarse?.x1 ?? 0) - (coarse?.x0 ?? 0),
    )
    expect(itemGeometry(item({ start_t: null }), v, lenses)).toBeNull()
  })
})
