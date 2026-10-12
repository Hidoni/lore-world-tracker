import { toPx, viewport } from '@lore/chronology/viewport'
import { describe, expect, it } from 'vitest'

import { absoluteTicks } from './absolute-ticks'

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }

describe('absolute ticks', () => {
  it('steps 1, 2, 5 × 10^k base units at least 64 px apart, majors at the next power of ten', () => {
    const found = absoluteTicks(viewport(0n, 1000n, 640), SECOND)
    const all = [...found.major, ...found.minor].sort((a, b) => (a.t < b.t ? -1 : 1))
    expect(all.map((tick) => tick.t)).toEqual([
      0n,
      100n,
      200n,
      300n,
      400n,
      500n,
      600n,
      700n,
      800n,
      900n,
    ])
    expect(found.major.map((tick) => tick.label)).toEqual(['0 s'])
    expect(found.minor[0]?.label).toBe('100 s')
  })

  it('stays exact and distinct across 100 orders of magnitude, negative moments included', () => {
    for (let k = 1n; k <= 100n; k += 3n) {
      const span = 10n ** k
      for (const start of [-span / 3n, 7n * 10n ** (k + 2n) + 12345n]) {
        const v = viewport(start, span, 960)
        const found = absoluteTicks(v, SECOND)
        const all = [...found.major, ...found.minor].sort((a, b) => (a.t < b.t ? -1 : 1))
        expect(all.length).toBeGreaterThan(0)
        expect(all.length).toBeLessThanOrEqual(100)
        for (const tick of all) {
          expect(tick.t >= v.start && tick.t < v.start + v.span).toBe(true)
          expect(tick.t % tick.multiple).toBe(0n)
        }
        const xs = all.map((tick) => toPx(v, tick.t))
        for (let i = 1; i < xs.length; i++) {
          expect((xs[i] ?? 0) - (xs[i - 1] ?? 0)).toBeGreaterThanOrEqual(63)
        }
        expect(new Set(all.map((tick) => tick.label)).size).toBe(all.length)
      }
    }
  })
})
