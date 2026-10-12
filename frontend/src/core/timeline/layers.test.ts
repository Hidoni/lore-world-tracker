import { rational } from '@lore/chronology'
import { viewport } from '@lore/chronology/viewport'
import { describe, expect, it } from 'vitest'

import { TickSnap } from './cursor-line'
import { eraShapes } from './era-bands'
import { overlayRows, phaseGlyph } from './overlay-strip'

describe('cursor snapping', () => {
  it('snaps to multiples of a base-unit step and steps between them, within the dimension', () => {
    const snap = new TickSnap(null, 'base', 10n, 100n)
    expect([14n, 15n, -4n, -6n, 99n].map((t) => snap.snap(t))).toEqual([10n, 20n, 0n, 0n, 100n])
    expect(snap.next(20n, 1)).toBe(30n)
    expect(snap.next(20n, -1)).toBe(10n)
    expect(snap.next(25n, -1)).toBe(20n)
    expect(snap.next(25n, 1)).toBe(30n)
    expect(snap.next(0n, -1)).toBe(0n)
    expect(snap.next(100n, 1)).toBe(100n)
  })
})

describe('overlay phases', () => {
  it('picks the nearest eighth of the cycle for a glyph', () => {
    expect(phaseGlyph(rational(0n))).toBe('🌑')
    expect(phaseGlyph(rational(1n, 4n))).toBe('🌓')
    expect(phaseGlyph(rational(7n, 16n))).toBe('🌕')
    expect(phaseGlyph(rational(15n, 16n))).toBe('🌑')
  })

  it('has nothing to draw without a calendar', () => {
    const v = viewport(0n, 1000n, 500)
    expect(overlayRows(null, v)).toEqual([])
    expect(eraShapes(null, v)).toEqual([])
  })
})
