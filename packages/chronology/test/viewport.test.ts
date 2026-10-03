// Viewport math and tiles (chronology-engine.md §12, frontend.md §9.2).
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import { rational } from '../src/numbers'
import {
  MIN_SPAN,
  OFFSCREEN_PX,
  type Viewport,
  clamp,
  fit,
  fromPx,
  marginOf,
  panBy,
  tileBounds,
  tileFor,
  toPx,
  viewport,
  zoomAt,
} from '../src/viewport'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 1000 : 200
const params = { numRuns: RUNS, seed: 20261003 }

/** Spans from 10 base units to 10^120, moments around them. */
const viewports: fc.Arbitrary<Viewport> = fc
  .record({
    start: fc.bigInt(-(10n ** 120n), 10n ** 120n),
    digits: fc.integer({ min: 1, max: 120 }),
    mantissa: fc.bigInt(1n, 9n),
    widthPx: fc.integer({ min: 1, max: 4000 }).map((w) => w + 0.5),
  })
  .map(({ start, digits, mantissa, widthPx }) =>
    viewport(start, mantissa * 10n ** BigInt(digits), widthPx),
  )

const pixels = fc.double({ min: -2000, max: 6000, noNaN: true })

describe('viewport', () => {
  test('toPx is monotonic', () => {
    fc.assert(
      fc.property(viewports, fc.bigInt(0n, 10n ** 121n), fc.bigInt(0n, 10n ** 121n), (v, a, b) => {
        const [t1, t2] = a < b ? [a, b] : [b, a]
        expect(toPx(v, v.start + t1 - 10n ** 120n) <= toPx(v, v.start + t2 - 10n ** 120n)).toBe(
          true,
        )
      }),
      params,
    )
  })

  test('fromPx(toPx(t)) is within one pixel of t', () => {
    fc.assert(
      fc.property(viewports, fc.bigInt(0n, 10n ** 6n), (v, fraction) => {
        const t = v.start + (v.span * fraction) / 10n ** 6n
        const back = fromPx(v, toPx(v, t))
        const pixel = v.span / BigInt(Math.floor(v.widthPx)) + 1n
        expect(back <= t && t - back <= pixel).toBe(true)
      }),
      params,
    )
  })

  test('zoomAt keeps the moment under the cursor exactly', () => {
    fc.assert(
      fc.property(viewports, pixels, fc.bigInt(1n, 1000n), fc.bigInt(1n, 1000n), (v, x, n, d) => {
        const zoomed = zoomAt(v, x, rational(n, d))
        expect(fromPx(zoomed, x)).toBe(fromPx(v, x))
        expect(zoomed.span >= MIN_SPAN).toBe(true)
      }),
      params,
    )
  })

  test('panBy moves by whole pixels and back', () => {
    fc.assert(
      fc.property(viewports, fc.integer({ min: -5000, max: 5000 }), (v, dx) => {
        const moved = panBy(v, dx)
        expect(fromPx(moved, 0)).toBe(fromPx(v, dx))
        expect(moved.span).toBe(v.span)
      }),
      params,
    )
  })

  test('fit shows the range with its padding', () => {
    fc.assert(
      fc.property(
        viewports,
        fc.bigInt(-(10n ** 100n), 10n ** 100n),
        fc.bigInt(0n, 10n ** 100n),
        fc.integer({ min: 0, max: 100 }),
        (v, start, length, padding) => {
          const fitted = fit(v, start, start + length, padding)
          expect(fitted.span >= MIN_SPAN).toBe(true)
          expect(fitted.start <= start).toBe(true)
          expect(fitted.start + fitted.span >= start + length).toBe(true)
          if (length > 10n ** 6n && 2 * padding < v.widthPx) {
            const left = toPx(fitted, start)
            const right = toPx(fitted, start + length)
            expect(Math.abs(left - padding)).toBeLessThan(2)
            expect(Math.abs(v.widthPx - right - padding)).toBeLessThan(2)
          }
        },
      ),
      params,
    )
  })

  test('clamp keeps the view on the dimension', () => {
    fc.assert(
      fc.property(viewports, fc.bigInt(100n, 10n ** 120n), (v, D) => {
        const clamped = clamp(v, D)
        expect(clamped.span >= MIN_SPAN && clamped.span <= (D * 5n) / 4n).toBe(true)
        const margin = marginOf(clamped.span, D)
        expect(clamped.start >= -margin).toBe(true)
        expect(clamped.start + clamped.span <= D + margin).toBe(true)
        expect(clamp(clamped, D)).toEqual(clamped)
      }),
      params,
    )
  })

  test('examples', () => {
    const v = viewport(1000n, 100n, 200)
    expect([toPx(v, 1000n), toPx(v, 1050n), toPx(v, 1100n)]).toEqual([0, 100, 200])
    expect(toPx(v, 10n ** 30n)).toBe(OFFSCREEN_PX)
    expect(toPx(v, -(10n ** 30n))).toBe(-OFFSCREEN_PX)
    expect(fromPx(v, 100)).toBe(1050n)
    expect(zoomAt(v, 100, rational(1n, 2n))).toEqual({ start: 1025n, span: 50n, widthPx: 200 })
    expect(zoomAt(v, 0, rational(1n, 100n)).span).toBe(MIN_SPAN)
    expect(panBy(v, -20)).toEqual({ ...v, start: 990n })
    expect(fit(v, 0n, 1000n, 50)).toEqual({ start: -500n, span: 2000n, widthPx: 200 })
    expect(fit(v, 0n, 1000n, 100).span).toBe(1000n) // no room for the padding: ignored
    expect(fit(v, 5n, 5n)).toEqual({ start: 0n, span: MIN_SPAN, widthPx: 200 })
    expect(viewport(0n, 1n, 10).span).toBe(MIN_SPAN)
    // the whole dimension and a margin of D/8 at most
    expect(clamp(viewport(-(10n ** 9n), 10n ** 9n, 100), 800n)).toEqual({
      start: -100n,
      span: 1000n,
      widthPx: 100,
    })
    expect(clamp(viewport(790n, 100n, 100), 800n).start).toBe(750n)
    expect(clamp(viewport(-90n, 100n, 100), 800n).start).toBe(-50n)
    expect(clamp(viewport(0n, 5n, 100), 3n).span).toBe(MIN_SPAN)
  })

  test('invalid input', () => {
    expect(() => viewport(0n, 100n, 0)).toThrow(RangeError)
    expect(() => toPx({ start: 0n, span: 100n, widthPx: Number.NaN }, 1n)).toThrow(RangeError)
    expect(() => zoomAt(viewport(0n, 100n, 10), 0, { num: 0n, den: 1n })).toThrow(RangeError)
  })
})

describe('tiles', () => {
  test('a viewport needs one to three tiles covering it', () => {
    fc.assert(
      fc.property(viewports, fc.bigInt(10n, 10n ** 120n), (v, D) => {
        const { z, size, indices } = tileFor(v, D)
        const expected = v.span >= D ? 0 : (D / v.span).toString(2).length - 1
        expect(z).toBe(expected)
        expect(size * (1n << BigInt(z)) >= D + 1n).toBe(true)
        const low = v.start < 0n ? 0n : v.start
        const high = v.start + v.span > D + 1n ? D + 1n : v.start + v.span
        if (low >= high) {
          expect(indices).toEqual([])
          return
        }
        expect(indices.length >= 1 && indices.length <= 3).toBe(true)
        const first = tileBounds(z, indices[0] ?? -1n, D)
        const last = tileBounds(z, indices.at(-1) ?? -1n, D)
        expect(first.start <= low && last.end >= high).toBe(true)
        indices.forEach((index, i) => {
          if (i > 0) expect(index).toBe((indices[i - 1] ?? 0n) + 1n)
        })
      }),
      params,
    )
  })

  test('examples', () => {
    expect(tileFor(viewport(0n, 1000n, 100), 1000n)).toEqual({ z: 0, size: 1001n, indices: [0n] })
    expect(tileFor(viewport(450n, 200n, 100), 1000n)).toEqual({
      z: 2,
      size: 251n,
      indices: [1n, 2n],
    })
    expect(tileBounds(2, 3n, 1000n)).toEqual({ start: 753n, end: 1001n })
    expect(tileFor(viewport(2000n, 200n, 100), 1000n).indices).toEqual([])
  })
})
