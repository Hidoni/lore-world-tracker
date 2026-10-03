// Calendar ticks (chronology-engine.md §12): properties over several calendars, label examples.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import { type CompiledCalendar, eraOf, fromFields, ordinal, unitBounds } from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import { type Tick, type Ticks, ticks, viewport } from '../src/viewport'
import { compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 300 : 40
const params = { numRuns: RUNS, seed: 20261003 }

function calendarOf(name: string, patches: Record<string, unknown> = {}): CompiledCalendar {
  const { definition, context } = load(name)
  return compiled(definition, patched(context, patches))
}

const CALENDARS = new Map<string, CompiledCalendar>([
  ['gregorian-seconds', calendarOf('gregorian-seconds')],
  ['mayan', calendarOf('preset-mayan')],
  ['alternating-years', calendarOf('alternating-years')],
  ['julian-gregorian', calendarOf('julian-gregorian')],
  ['japanese-eras', calendarOf('japanese-eras')],
  ['shire-week', calendarOf('shire-week')],
  ['intercalary-exceptions', calendarOf('intercalary-exceptions')],
  ['10^110 s', calendarOf('gregorian-seconds', { '/dimension_duration': String(10n ** 110n) })],
])
const calendar = (name: string): CompiledCalendar => defined(CALENDARS.get(name))
const GREGORIAN = calendar('gregorian-seconds')
const DAY = 86400n

function g(year: number, month: string, day: number, hour = 0): bigint {
  const fields = { year: String(year), month, day: String(day), hour: String(hour) }
  return fromFields(GREGORIAN, fields, 'hour')
}

const labels = (found: readonly Tick[]): string[] => found.map((tick) => tick.label)

/** The year number ticks align on: the era year, else the astronomical year. */
function yearNumber(c: CompiledCalendar, t: bigint): bigint {
  return eraOf(c, t)?.year ?? ordinal(c, t, defined(c.levels.at(-1))).value
}

function checkTick(c: CompiledCalendar, tick: Tick): void {
  const top = defined(c.levels.at(-1))
  expect(tick.label).not.toBe('')
  if (tick.level === 'base') {
    const start = unitBounds(c, tick.t, defined(c.levels[0])).start
    expect((tick.t - start) % tick.multiple).toBe(0n)
    expect(tick.t).not.toBe(start)
    return
  }
  expect(unitBounds(c, tick.t, tick.level).start).toBe(tick.t)
  const eraStart = c.eras.some((era) => era.start === tick.t)
  if (tick.level === top && !eraStart) {
    expect(yearNumber(c, tick.t) % tick.multiple).toBe(0n)
  } else if (tick.multiple > 1n && tick.level !== top) {
    const found = ordinal(c, tick.t, tick.level)
    expect(found.counted).toBe(true)
    expect(found.value % tick.multiple).toBe(0n)
  }
}

function checkTicks(c: CompiledCalendar, found: Ticks, start: bigint, span: bigint, max: number) {
  const all = [...found.major, ...found.minor]
  expect(all.length).toBeLessThanOrEqual(max)
  for (const list of [found.major, found.minor]) {
    list.forEach((tick, i) => {
      expect(tick.t >= start && tick.t < start + span).toBe(true)
      if (i > 0) expect(defined(list[i - 1]).t < tick.t).toBe(true)
    })
  }
  const majors = new Set(found.major.map((tick) => tick.t))
  expect(found.minor.some((tick) => majors.has(tick.t))).toBe(false)
  for (const tick of all) checkTick(c, tick)
}

describe('properties', () => {
  const cases = fc
    .record({
      name: fc.constantFrom(...CALENDARS.keys()),
      position: fc.bigInt(0n, 10n ** 6n),
      digits: fc.integer({ min: 1, max: 1000 }),
      mantissa: fc.bigInt(1n, 9n),
      widthPx: fc.integer({ min: 100, max: 3000 }),
      minSpacingPx: fc.integer({ min: 20, max: 200 }),
      maxTicks: fc.integer({ min: 1, max: 200 }),
    })
    .map((drawn) => {
      const c = calendar(drawn.name)
      const D = BigInt(c.context.dimension_duration)
      const longest = (D * 5n) / 4n
      let span = drawn.mantissa * 10n ** BigInt(drawn.digits % (D.toString().length + 1))
      if (span > longest) span = longest
      if (span < 10n) span = 10n
      const start = (D * drawn.position) / 10n ** 6n - span / 2n
      return { ...drawn, c, start, span }
    })

  test('ticks are sorted, inside the viewport, aligned and within maxTicks', () => {
    fc.assert(
      fc.property(cases, ({ c, start, span, widthPx, minSpacingPx, maxTicks }) => {
        const found = ticks(c, viewport(start, span, widthPx), { minSpacingPx, maxTicks })
        checkTicks(c, found, start, span, maxTicks)
      }),
      params,
    )
  })
})

describe('Gregorian', () => {
  const at = (start: bigint, span: bigint, width = 1200) =>
    ticks(GREGORIAN, viewport(start, span, width), { minSpacingPx: 64, maxTicks: 100 })

  test('hours with days as major ticks', () => {
    const found = at(g(2024, 'mar', 15, 14), 2n * DAY)
    expect(labels(found.major)).toEqual(['16 March 2024', '17 March 2024'])
    expect(labels(found.minor).slice(0, 3)).toEqual(['15:00', '18:00', '21:00'])
    expect(found.minor[0]?.multiple).toBe(3n)
  })

  test('minutes, seconds and the clock', () => {
    const minutes = at(g(2024, 'mar', 15, 14), 7200n)
    expect(labels(minutes.minor).slice(0, 2)).toEqual(['14:10', '14:20'])
    const seconds = at(g(2024, 'mar', 15, 14), 30n)
    expect(labels(seconds.minor).slice(0, 2)).toEqual(['14:00:02', '14:00:04'])
  })

  test('months with years as major ticks', () => {
    const found = at(g(2024, 'mar', 15), 400n * DAY)
    expect(labels(found.major)).toEqual(['2025'])
    expect(labels(found.minor).slice(0, 2)).toEqual(['April', 'May'])
  })

  test('days are aligned on their ordinal', () => {
    const found = at(g(2024, 'mar', 15), 40n * DAY)
    expect(labels(found.major)).toEqual(['April 2024'])
    for (const tick of found.minor) expect(ordinal(GREGORIAN, tick.t, 'day').value % 3n).toBe(0n)
  })

  test('decades and centuries', () => {
    const found = at(g(2024, 'jan', 1), 30n * 366n * DAY)
    expect(labels(found.major)).toEqual(['2030', '2040', '2050'])
    expect(labels(found.minor).slice(0, 2)).toEqual(['2024', '2026']) // the start is a tick
  })

  test('maxTicks raises the multiple', () => {
    const found = ticks(GREGORIAN, viewport(g(2024, 'mar', 15), 400n * DAY, 1200), {
      minSpacingPx: 10,
      maxTicks: 6,
    })
    expect(found.major.length + found.minor.length).toBeLessThanOrEqual(6)
    expect(found.minor.every((tick) => tick.level === 'month' && tick.multiple > 1n)).toBe(true)
  })

  test('an invalid width', () => {
    expect(() => ticks(GREGORIAN, { start: 0n, span: 100n, widthPx: 0 })).toThrow(RangeError)
    expect(() => ticks(GREGORIAN, { start: 0n, span: 100n, widthPx: Number.NaN })).toThrow(
      RangeError,
    )
  })

  test('a budget of one tick', () => {
    const found = ticks(GREGORIAN, viewport(g(2024, 'jan', 1), 10n ** 15n, 1200), { maxTicks: 1 })
    expect(found.major.length + found.minor.length).toBeLessThanOrEqual(1)
  })
})

describe('labels and decisions (2026-10-03)', () => {
  test('era years with their era, era starts as major ticks', () => {
    const c = calendar('julian-gregorian')
    const start = fromFields(c, { year: '500', month: 'jan', day: '1' }, 'day', { era: 'bc' })
    const found = ticks(c, viewport(start, 1000n * 366n * DAY, 1200), { minSpacingPx: 64 })
    expect(labels(found.major)).toEqual(['AD 1'])
    expect(labels(found.minor)).toEqual([
      '500 BC',
      '400 BC',
      '300 BC',
      '200 BC',
      '100 BC',
      'AD 100',
      'AD 200',
      'AD 300',
      'AD 400',
      'AD 500',
    ])
  })

  test('intercalary units get ticks at multiple 1', () => {
    const shire = calendar('shire-week')
    const found = ticks(shire, viewport(10_000_000n, 366n, 3000), { minSpacingPx: 60 })
    expect(labels(found.minor)).toContain("Midyear's Day")
    expect(labels(found.minor)).toContain('1 Lithe')
    expect(found.minor.every((tick) => tick.level === 'month' && tick.multiple === 1n)).toBe(true)
  })

  test('base-unit ticks show the offset in the finest unit', () => {
    const c = calendar('intercalary-exceptions')
    const found = ticks(c, viewport(1_000_000n, 48n, 1200), { minSpacingPx: 64 })
    expect(labels(found.minor).slice(0, 4)).toEqual(['+5 h', '+10 h', '+15 h', '+20 h'])
    expect(found.major.map((tick) => tick.level)).toEqual(['day', 'day'])
  })

  test('huge years keep the digits that tell ticks apart', () => {
    const c = calendar('alternating-years')
    const D = BigInt(c.context.dimension_duration)
    const found = ticks(c, viewport(D / 2n, D / 10n ** 5n, 1200))
    const minor = labels(found.minor)
    expect(new Set(minor).size).toBe(minor.length)
    expect(minor[0]).toMatch(/^6\.3246\d × 10\^102$/)
  })

  test('the whole of a 10^110-second dimension', () => {
    const c = calendar('10^110 s')
    const D = BigInt(c.context.dimension_duration)
    const found = ticks(c, viewport(0n, D, 1200))
    expect(labels(found.major)).toEqual(['0', '1 × 10^102', '2 × 10^102', '3 × 10^102'])
    expect(found.minor[0]?.label).toBe('2 × 10^101')
  })

  test('each regime is ticked separately', () => {
    const c = calendar('julian-gregorian')
    const start = fromFields(c, { year: '1582', month: 'sep', day: '21' }, 'day')
    const found = ticks(c, viewport(start, 30n * DAY, 1200), { minSpacingPx: 64 })
    // Julian 4 October is followed by Gregorian 15 October (the reform starts a month unit)
    expect(labels(found.minor)).toContain('4')
    expect(labels(found.minor)).toContain('16')
    expect(labels(found.major)).toEqual(['October AD 1582', 'October AD 1582'])
  })

  test('huge years far from a major tick are labeled as offsets', () => {
    const c = calendar('mayan')
    const D = BigInt(c.context.dimension_duration)
    const baktun = 20n * 20n * 18n * 20n * DAY // 144,000 days
    const found = ticks(c, viewport(D / 3n, 20n * baktun, 1200))
    expect(found.minor.every((tick) => tick.level === 'baktun' && tick.multiple === 2n)).toBe(true)
    expect(new Set(labels(found.minor))).toEqual(new Set(['+2', '+4', '+6', '+8']))
    for (const tick of found.major) expect(tick.label).toMatch(/^2\.6791838134\d+ × 10\^109$/)
  })

  test('top-level multiples grow 1, 2, 5, 10 until maxTicks holds', () => {
    const start = g(2001, 'jan', 1)
    const wide = { minSpacingPx: 400 }
    const single = ticks(GREGORIAN, viewport(start, 5n * 365n * DAY, 3000), wide)
    expect(single.minor.every((tick) => tick.level === 'year' && tick.multiple === 1n)).toBe(true)
    expect(labels(single.minor)).toEqual(['2001', '2002', '2003', '2004', '2005'])
    const capped = ticks(GREGORIAN, viewport(start, 99n * 366n * DAY, 3000), {
      minSpacingPx: 1,
      maxTicks: 4,
    })
    expect(capped.minor.map((tick) => tick.multiple)).toEqual([50n])
    expect(labels(capped.major)).toEqual(['2100'])
  })

  test('huge BC years count their offsets back from the preceding major tick', () => {
    const c = calendar('julian-gregorian')
    const found = ticks(c, viewport(-(10n ** 30n), 40n * 366n * DAY, 1200))
    expect(found.minor.length).toBeGreaterThan(0)
    for (const tick of found.minor) {
      expect(tick.label).toMatch(/^\+\d$/)
      const era = defined(eraOf(c, tick.t))
      expect(era.id).toBe('bc')
      expect(BigInt(tick.label.slice(1))).toBe((10n - (era.year % 10n)) % 10n)
    }
    expect(found.major.every((tick) => tick.label.endsWith(' BC'))).toBe(true)
  })

  test('a one-level clock shows the number and abbreviation', () => {
    const c = calendarOf('formats-showcase')
    const { definition, context } = load('formats-showcase')
    const renumbered = compiled(
      patched(definition, {
        '/levels/1/numbering_start': 1,
        '/regimes/0/alignment/fields/hour': '1',
      }),
      context,
    )
    const D = BigInt(c.context.dimension_duration)
    const found = ticks(renumbered, viewport(D / 2n, 3600n, 1200), { minSpacingPx: 64 })
    expect(found.minor.length).toBeGreaterThan(0)
    for (const tick of found.minor) expect(tick.label).toMatch(/^\d+ min$/)
  })

  test('performance stays well within a frame', () => {
    const begun = performance.now()
    let runs = 0
    for (const [, c] of CALENDARS) {
      const D = BigInt(c.context.dimension_duration)
      for (let digits = 2; digits < D.toString().length; digits += 7) {
        ticks(c, viewport(D / 3n, 10n ** BigInt(digits), 1500))
        runs++
      }
    }
    // the < 2 ms target is measured by test/ticks.bench.ts; this guards against regressions
    expect((performance.now() - begun) / runs).toBeLessThan(10)
  })
})
