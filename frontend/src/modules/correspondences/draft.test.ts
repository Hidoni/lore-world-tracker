import { describe, expect, it } from 'vitest'

import { lenses } from '@/core/time'
import { presetCalendar, testDimension } from '@/test/calendars'

import {
  chartRange,
  chartSamples,
  helperRate,
  levelLength,
  NO_RATE,
  previewOf,
  rateOf,
} from './draft'

const DAY = 86_400n
const point = (t: bigint) => ({
  anchor: { kind: 'absolute' as const, t: t.toString() },
  precision: 'base' as const,
})

describe('correspondence drafts', () => {
  const dimension = testDimension('gregorian')
  const all = lenses(dimension, [presetCalendar('gregorian', 'gregorian')])
  const [gregorian] = all
  const absolute = all.at(-1)

  it('measures calendar levels where the sync point is', () => {
    if (gregorian === undefined || absolute === undefined) throw new Error('no lenses')
    expect(levelLength(gregorian, 'day', 0n)).toBe(DAY)
    // A common year from 1 January AD 1, and a month there (January).
    expect(levelLength(gregorian, 'year', 0n)).toBe(365n * DAY)
    expect(levelLength(gregorian, 'month', 0n)).toBe(31n * DAY)
    expect(levelLength(absolute, null, 123n)).toBe(1n)
  })

  it('turns "1 day here = 1 year there" into a rate', () => {
    const rate = helperRate(1n, DAY, 1n, 365n * DAY)
    expect(rate).toEqual({ num: 365n, den: 1n })
    expect(helperRate(2n, DAY, 3n, DAY)).toEqual({ num: 3n, den: 2n })
    expect(helperRate(0n, DAY, 1n, DAY)).toBeNull()
    expect(rateOf({ num: 6n, den: 4n })).toEqual({ num: 3n, den: 2n })
    expect(rateOf({ num: 6n, den: null })).toBeNull()
  })

  it('previews drafts the browser can place, like the server would', () => {
    if (absolute === undefined) throw new Error('no lenses')
    const draft = (a: bigint, b: bigint) => ({ key: `${a}`, a: point(a), b: point(b) })
    const ok = previewOf([draft(100n, 1000n), draft(200n, 3000n)], [absolute], [absolute],
      'none', NO_RATE, NO_RATE) // prettier-ignore
    expect(ok.kind).toBe('ok')
    if (ok.kind !== 'ok') return
    expect(ok.correspondence.mapAB(150n, 10_000n)).toBe(2000n)
    expect(chartRange(ok.correspondence, 10_000n)).toEqual([100n, 200n])
    const samples = chartSamples(ok.correspondence, 100n, 200n, 10_000n, 4)
    expect(samples.map(([a, b]) => [a, b])).toEqual([
      [100n, 1000n],
      [125n, 1500n],
      [150n, 2000n],
      [175n, 2500n],
      [200n, 3000n],
    ])
    const backwards = previewOf([draft(100n, 1000n), draft(200n, 500n)], [absolute], [absolute],
      'none', NO_RATE, NO_RATE) // prettier-ignore
    expect(backwards.kind).toBe('invalid')
    const relative = {
      key: 'r',
      a: {
        anchor: {
          kind: 'relative' as const,
          ref: { type: 'event', id: 'e1', slot: 'start' },
          offset: { kind: 'base' as const, units: '0' },
        },
        precision: 'base' as const,
      },
      b: point(1n),
    }
    expect(previewOf([relative], [absolute], [absolute], 'none', NO_RATE, NO_RATE).kind).toBe(
      'pending',
    )
  })

  it('widens the chart when extrapolating, within the dimension', () => {
    if (absolute === undefined) throw new Error('no lenses')
    const preview = previewOf([{ key: 'a', a: point(100n), b: point(0n) }], [absolute],
      [absolute], 'rate', { num: 2n, den: 1n }, { num: 2n, den: 1n }) // prettier-ignore
    if (preview.kind !== 'ok') throw new Error(preview.kind)
    expect(chartRange(preview.correspondence, 1000n)).toEqual([0n, 200n])
  })
})
