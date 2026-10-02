// Calendar compilation (chronology-engine.md §4, §5.1–§5.4), mirroring the Python engine's
// backend/tests/chronology/test_calendar_compile.py. Error codes are covered by the vectors.
// Property tests are seeded; PROPERTY_PROFILE=ci runs more examples (like hypothesis' `ci`).
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  CompiledCalendar,
  compileCalendar,
  pointer,
  type ValidationError,
  validateCalendar,
} from '../src/calendar'
import { bisectLeft, bisectRight, defined } from '../src/calendar/compiled'
import { patternTokens, unknownTokens } from '../src/calendar/formats'
import type { CalendarDefinition, CompileContext } from '../src/schema.gen'
import { at, compiled, errorsOf, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261002 }
const DAY = 86_400n

const GREGORIAN = load('gregorian-seconds')
const ALTERNATING = load('alternating-years')
const G = GREGORIAN.context
const REGIME = '/regimes/0'
const MONTHS = '/levels/4/default_template' // the month level's default template

/** The regime-0 templates of a definition, with `extra` added. */
function withTemplates(definition: unknown, extra: Readonly<Record<string, unknown>>): unknown {
  const templates = at(definition, `${REGIME}/templates`) as Record<string, unknown>
  return patched(definition, { [`${REGIME}/templates`]: { ...templates, ...extra } })
}

/** Gregorian plus exception years with longer, shorter and equal lengths, around year 0. */
function gregorianWithExceptions(): CompiledCalendar {
  const definition = patched(
    withTemplates(GREGORIAN.definition, {
      year_short: { level: 'year', sequence: [{ id: 'jan', template: 'm31', name: 'January' }] },
    }),
    {
      [`${REGIME}/top/exceptions`]: [
        { year: '-401', template: 'year_leap' },
        { year: '-4', template: 'year_short' },
        { year: '0', template: 'year_common' },
        { year: '7', template: 'year_short' },
        { year: '1582', template: 'year_short' },
        { year: '2000', template: 'year_leap' },
      ],
    },
  )
  return compiled(definition, G)
}

const EXCEPTIONS = gregorianWithExceptions()
const mod = (a: number, b: number): number => ((a % b) + b) % b

// --- compiled structure --------------------------------------------------------------------------

describe('compiled structure', () => {
  test('gregorian', () => {
    const calendar = compiled(GREGORIAN.definition, G)
    const regime = defined(calendar.regimes[0])
    expect(calendar.levels).toEqual(['second', 'minute', 'hour', 'day', 'month', 'year'])
    expect(calendar.numberingStarts).toEqual([0n, 0n, 0n, 1n, 1n, 1n])
    expect([regime.period, regime.cycleLength]).toEqual([400n, 146_097n * DAY])
    expect(regime.epoch).toBe(10n ** 14n - 730_485n * DAY) // 0000-01-01 → 2000-01-01
    expect(regime.yearStart(2000n)).toBe(10n ** 14n)
    expect(regime.yearOf(10n ** 14n)).toBe(2000n)
    expect(regime.yearOf(10n ** 14n - 1n)).toBe(1999n)
    expect([1900n, 2000n, 2024n, 2023n, -4n].map((y) => regime.regularTemplate(y))).toEqual([
      'year_common',
      'year_leap',
      'year_leap',
      'year_common',
      'year_leap',
    ])
    const leap = regime.template('year_leap')
    expect([leap.length, leap.totalCount, leap.regularCount]).toEqual([366n * DAY, 12n, 12n])
    expect(leap.units.get(calendar.levelIndex('day'))).toEqual([366n, 366n])
    expect(leap.units.get(0)).toEqual([366n * DAY, 366n * DAY])
    expect(regime.template('second').units.size).toBe(0)
    expect(calendar.levelIndex('week')).toBe(-1)
    expect(() => regime.template('nope')).toThrow('unknown template nope')
  })

  test('alternating years', () => {
    const regime = defined(compiled(ALTERNATING.definition, ALTERNATING.context).regimes[0])
    expect([regime.period, regime.cycleLength]).toEqual([2n, 183n * DAY])
    expect(regime.epoch).toBe(435_000_000_000_000_000n - 92n * DAY)
    expect([-1n, 0n, 1n, 2n].map((y) => regime.regularTemplate(y))).toEqual([
      'year_odd',
      'year_even',
      'year_odd',
      'year_even',
    ])
  })

  test('template children', () => {
    const definition = patched(
      withTemplates(GREGORIAN.definition, {
        m1: { level: 'month', uniform: { count: '1' } },
        year_common: {
          level: 'year',
          sequence: [
            { id: 'jan', template: 'm31', name: 'January', abbr: 'Jan' },
            { id: 'midyear', template: 'm1', name: 'Midyear', intercalary: true },
            { run: { count: '3', template: 'm30' } },
            { id: 'dec', template: 'm31', name: 'December' },
          ],
        },
      }),
      { [MONTHS]: 'm30' },
    )
    const template = defined(compiled(definition, G).regimes[0]).template('year_common')
    expect([template.totalCount, template.regularCount]).toEqual([6n, 5n])
    expect(template.units.get(4)).toEqual([6n, 5n]) // months: Midyear is intercalary
    expect(template.units.get(3)).toEqual([31n + 1n + 90n + 31n, 31n + 1n + 90n + 31n])
    const midyear = defined(template.childBySlot('midyear'))
    expect([midyear.offset, midyear.segment.intercalary, midyear.segment.childLength]).toEqual([
      31n * DAY,
      true,
      DAY,
    ])
    expect(template.childBySlot('jan')?.segment.abbr).toBe('Jan')
    expect(template.childBySlot('feb')).toBeNull()
    const third = defined(template.childByRegularIndex(3n)) // 0-based: jan, run[0], run[1], run[2]
    expect([third.offset, third.index]).toEqual([32n * DAY + 60n * DAY, 2n])
    expect(template.childByRegularIndex(5n)).toBeNull()
    expect(template.childByRegularIndex(-1n)).toBeNull()
    const inside = template.childAt(32n * DAY + 45n * DAY)
    expect([inside.offset, inside.segment.child]).toEqual([32n * DAY + 30n * DAY, 'm30'])
    expect(template.childAt(31n * DAY).segment.slotId).toBe('midyear')
  })

  test('compileCalendar takes schema-valid documents', () => {
    const definition = GREGORIAN.definition as CalendarDefinition
    const context = G as CompileContext
    expect(compileCalendar(definition, context)).toBeInstanceOf(CompiledCalendar)
    const errors = compileCalendar(definition, { ...context, resolved: {} }) as ValidationError[]
    expect(errors).toEqual([
      {
        code: 'anchor.unresolved',
        path: '/regimes/0/alignment/at',
        message: 'no resolved moment in the context',
      },
    ])
  })

  test('a cycle pattern with exceptions and many templates', () => {
    const extra: Record<string, unknown> = {}
    const templates: string[] = []
    for (let i = 0; i < 300; i++) {
      // more templates than fit one byte
      extra[`y${i}`] = {
        level: 'year',
        sequence: [{ run: { count: String(1 + (i % 3)), template: 'm30' } }],
      }
      templates.push(`y${i}`)
    }
    const definition = patched(withTemplates(ALTERNATING.definition, extra), {
      [MONTHS]: 'm30',
      [`${REGIME}/top/pattern`]: { kind: 'cycle', templates, start: '-5' },
      [`${REGIME}/alignment/fields`]: { year: '1' },
    })
    const result = defined(compiled(definition, ALTERNATING.context).regimes[0])
    expect(result.period).toBe(300n)
    expect(result.topSequence).toBeInstanceOf(Uint16Array)
    expect([-5n, -4n, 294n, 295n].map((y) => result.regularTemplate(y))).toEqual([
      'y0',
      'y1',
      'y299',
      'y0',
    ])
    for (let year = -310n; year < 310n; year += 7n) {
      expect(result.relStart(year + 1n) - result.relStart(year)).toBe(
        result.yearTemplate(year).length,
      )
    }
  })

  test('rules with many templates match a per-year evaluation', () => {
    const common = at(GREGORIAN.definition, `${REGIME}/templates/year_common`)
    const extra: Record<string, unknown> = {}
    const rules: unknown[] = []
    for (let i = 0; i < 260; i++) {
      extra[`y${i}`] = common
      rules.push({ when: { mod: String(2 + (i % 7)), eq: String(i % 2) }, template: `y${i}` })
    }
    rules.push({
      when: { all: [{ not: { any: [{ mod: '4', eq: '1' }] } }, { mod: '1', eq: '0' }] },
      template: 'year_leap',
    })
    const definition = patched(withTemplates(GREGORIAN.definition, extra), {
      [`${REGIME}/top/pattern`]: { kind: 'rules', default: 'year_common', rules },
    })
    const result = defined(compiled(definition, G).regimes[0])
    expect(result.period).toBe(840n) // lcm(2, …, 8)
    expect(result.topSequence).toBeInstanceOf(Uint16Array)
    const expected = (year: number): string => {
      for (let i = 0; i < 260; i++) {
        if (mod(year, 2 + (i % 7)) === i % 2) return `y${i}`
      }
      return mod(year, 4) !== 1 ? 'year_leap' : 'year_common'
    }
    for (let year = -840; year < 840; year++) {
      expect(result.regularTemplate(BigInt(year))).toBe(expected(year))
    }
  })

  test('rules with combined predicates match a per-year evaluation', () => {
    const definition = patched(
      withTemplates(GREGORIAN.definition, {
        year_short: { level: 'year', sequence: [{ id: 'jan', template: 'm31', name: 'January' }] },
      }),
      {
        [`${REGIME}/top/pattern/rules/-`]: {
          when: { all: [{ mod: '3', eq: '2' }, { not: { mod: '5', eq: '0' } }] },
          template: 'year_short',
        },
      },
    )
    const result = defined(compiled(definition, G).regimes[0])
    expect(result.period).toBe(1200n) // lcm(4, 100, 400, 3, 5)
    expect(result.topSequence).toBeInstanceOf(Uint8Array)
    const expected = (year: number): string => {
      if ((mod(year, 4) === 0 && mod(year, 100) !== 0) || mod(year, 400) === 0) return 'year_leap'
      if (mod(year, 3) === 2 && mod(year, 5) !== 0) return 'year_short'
      return 'year_common'
    }
    for (let year = -6000; year < 6000; year += 7) {
      expect(result.regularTemplate(BigInt(year))).toBe(expected(year))
    }
  })
})

// --- properties (chronology-engine §5.2, §5.3) ---------------------------------------------------

const years = fc.oneof(
  fc.bigInt({ min: -2100n, max: 2100n }),
  fc.constantFrom(
    ...[-402, -401, -400, -5, -4, -3, -1, 0, 1, 6, 7, 8, 1581, 1582, 1583, 1999, 2000, 2001].map(
      BigInt,
    ),
  ),
  fc.bigInt({ min: -(10n ** 200n), max: 10n ** 200n }),
)

describe('year starts (properties)', () => {
  const regime = defined(EXCEPTIONS.regimes[0])

  test('consecutive year starts differ by the year length', () => {
    fc.assert(
      fc.property(years, (year) => {
        expect(regime.relStart(year + 1n) - regime.relStart(year)).toBe(
          regime.yearTemplate(year).length,
        )
      }),
      params,
    )
  })

  test('yearOfRel inverts the year starts', () => {
    fc.assert(
      fc.property(years, fc.bigInt({ min: 0n, max: 400n * DAY }), (year, offset) => {
        const rel = regime.relStart(year) + offset
        const found = regime.yearOfRel(rel)
        expect(regime.relStart(found) <= rel).toBe(true)
        expect(rel < regime.relStart(found) + regime.yearTemplate(found).length).toBe(true)
      }),
      params,
    )
  })

  test('year 0 starts at the epoch', () => {
    expect(regime.relStart(0n)).toBe(0n)
    expect(regime.yearOfRel(-1n)).toBe(-1n)
    expect(regime.yearTemplate(7n).id).toBe('year_short')
    expect(regime.yearTemplate(0n).id).toBe('year_common') // an exception equal to the rule
    expect(regime.yearTemplate(4n).id).toBe('year_leap')
    expect(regime.yearOfRel(regime.relStart(-1000n))).toBe(-1000n) // before every exception
  })
})

// --- helpers -------------------------------------------------------------------------------------

describe('helpers', () => {
  test('format tokens', () => {
    expect(patternTokens('{{literal}} {day:pad2}, {month.name}')).toEqual([
      'day:pad2',
      'month.name',
    ])
    const scope = {
      levels: new Set(['day', 'month']),
      cycles: new Set(['week']),
      overlays: new Set<string>(),
    }
    expect(unknownTokens('{day.name:pad2} {cycle.moon} {overlay.x} {year.name} {}', scope)).toEqual(
      ['day.name:pad2', 'cycle.moon', 'overlay.x', 'year.name', ''],
    )
    const known = '{era} {era.name} {cycle.week.n} {year:ordinal} {day.abbr} {month:pad2}'
    expect(unknownTokens(known, scope)).toEqual([])
    expect(unknownTokens('}{day}', scope)).toEqual(['{'])
    expect(unknownTokens('{day', scope)).toEqual(['{'])
  })

  test('pointer escapes', () => {
    expect(pointer('formats', 'a/b', 'c~d', 3)).toBe('/formats/a~1b/c~0d/3')
    expect(pointer()).toBe('')
  })

  test('bisection', () => {
    const values = [1n, 3n, 3n, 7n]
    expect([0n, 1n, 3n, 4n, 9n].map((v) => bisectRight(values, v))).toEqual([0, 1, 3, 3, 4])
    expect([0n, 1n, 3n, 4n, 9n].map((v) => bisectLeft(values, v))).toEqual([0, 0, 1, 3, 4])
    expect(bisectRight(values, 9n, 2)).toBe(2)
  })

  test('defined', () => {
    expect(defined(0)).toBe(0)
    expect(() => defined<number>(undefined)).toThrow('invariant')
    expect(() => defined<number>(null)).toThrow('invariant')
  })
})

// --- raw documents -------------------------------------------------------------------------------
// Expected errors were cross-checked against the Python engine's validate_calendar.

describe('validateCalendar', () => {
  test('reports schema errors with pointers, context errors under /$context', () => {
    const definition = patched(GREGORIAN.definition, {
      [`${REGIME}/alignment/at/anchor/t`]: '01',
      [`${REGIME}/templates/m30/uniform/count`]: 'x',
    })
    expect(errorsOf(definition, { base_unit: 's', dimension_duration: '0' })).toEqual([
      { code: 'schema.invalid', path: '/$context/base_unit' },
      { code: 'schema.invalid', path: '/$context/dimension_duration' },
      { code: 'schema.invalid', path: '/regimes/0/alignment/at/anchor/t' },
      { code: 'schema.invalid', path: '/regimes/0/templates/m30/uniform/count' },
    ])
  })

  test('rejects non-objects', () => {
    expect(errorsOf([], G)).toEqual([{ code: 'schema.invalid', path: '' }])
    const nested = {
      schema_version: 1,
      levels: [],
      regimes: ['x', { templates: { t: 'x' } }],
      eras: ['x'],
    }
    const paths = new Set(errorsOf(nested, G).map((e) => e.path))
    for (const path of ['/levels', '/regimes/0', '/eras/0']) expect(paths).toContain(path)
  })

  test('too many templates', () => {
    const extra: Record<string, unknown> = {}
    const count = Object.keys(at(GREGORIAN.definition, `${REGIME}/templates`) as object).length
    for (let i = count; i < 501; i++)
      extra[`extra${i}`] = { level: 'day', uniform: { count: '24' } }
    expect(errorsOf(withTemplates(GREGORIAN.definition, extra), G)).toEqual([
      { code: 'template.too_large', path: '/regimes/0/templates' },
    ])
  })

  test('too many children', () => {
    const definition = patched(GREGORIAN.definition, {
      [`${REGIME}/templates/year_common/sequence`]: Array.from({ length: 10_001 }, () => ({
        run: { count: '1', template: 'm30' },
      })),
    })
    expect(errorsOf(definition, G)).toEqual([
      { code: 'template.too_large', path: '/regimes/0/templates/year_common/sequence' },
    ])
  })

  test('rationals must be normalized', () => {
    const definition = patched(GREGORIAN.definition, {
      '/overlays': [
        {
          id: 'moon',
          name: 'Moon',
          period: { num: '4', den: '2' },
          epoch: { anchor: { kind: 'local', fields: { year: '1' } }, precision: 'year' },
          phases: [{ name: 'New', from: { num: '0', den: '1' } }],
        },
      ],
    })
    expect(errorsOf(definition, G)).toEqual([
      { code: 'schema.invalid', path: '/overlays/0/period' },
    ])
  })

  test('mapping keys follow their pattern and length limit', () => {
    const long = `t${'x'.repeat(64)}`
    const definition = withTemplates(GREGORIAN.definition, {
      Bad: { level: 'day', uniform: { count: '24' } },
      [long]: { level: 'day', uniform: { count: '24' } },
    })
    const context = patched(G, { '/resolved': { 'no-slash': '0' } })
    expect(errorsOf(definition, context)).toEqual([
      { code: 'schema.invalid', path: '/$context/resolved/no-slash' },
      { code: 'schema.invalid', path: '/regimes/0/templates/Bad' },
      { code: 'schema.invalid', path: `/regimes/0/templates/${long}` },
    ])
  })

  test('unions report the branches that fit the value', () => {
    const definition = patched(GREGORIAN.definition, {
      [`${REGIME}/templates/day/uniform/count`]: 24, // the uniform branch fits: only its error
      [`${REGIME}/top/pattern`]: { kind: 'weekly' }, // unknown discriminator tag
      [`${REGIME}/alignment/at/anchor`]: { t: '0' }, // no discriminator
      [`${REGIME}/templates/year_common/sequence/0`]: { id: 'jan' }, // fits neither child shape
      [`${REGIME}/cycles`]: [{ id: 'week', level: 'day', length: 7, mode: 'weekly' }],
    })
    const sequence = '/regimes/0/templates/year_common/sequence/0'
    expect(errorsOf(definition, G)).toEqual([
      { code: 'schema.invalid', path: '/regimes/0/alignment/at/anchor' },
      { code: 'schema.invalid', path: '/regimes/0/cycles/0/mode' },
      { code: 'schema.invalid', path: '/regimes/0/templates/day/uniform/count' },
      { code: 'schema.invalid', path: `${sequence}/id` },
      { code: 'schema.invalid', path: `${sequence}/name` },
      { code: 'schema.invalid', path: `${sequence}/run` },
      { code: 'schema.invalid', path: `${sequence}/template` },
      { code: 'schema.invalid', path: '/regimes/0/top/pattern' },
    ])
  })

  test('scalar constraints', () => {
    const definition = patched(GREGORIAN.definition, {
      '/schema_version': 2,
      '/levels/0/numbering_start': -1,
      '/levels/1/numbering_start': 1.5,
      '/levels/2/label': '',
      '/levels/3/abbr': null, // nullable: valid
      [`${REGIME}/name`]: '😀'.repeat(200), // 200 code points: valid
      [`${REGIME}/id`]: 'é',
      '/eras': [{ id: 'x', name: 'X', abbr: 'X', numbering: { direction: 'up', first: '1' } }],
      '/display': { significant_digits: 51, digit_group: true },
    })
    expect(errorsOf(definition, G)).toEqual([
      { code: 'schema.invalid', path: '/display/digit_group' },
      { code: 'schema.invalid', path: '/display/significant_digits' },
      { code: 'schema.invalid', path: '/eras/0/numbering/direction' },
      { code: 'schema.invalid', path: '/levels/0/numbering_start' },
      { code: 'schema.invalid', path: '/levels/1/numbering_start' },
      { code: 'schema.invalid', path: '/levels/2/label' },
      { code: 'schema.invalid', path: '/regimes/0/id' },
      { code: 'schema.invalid', path: '/schema_version' },
    ])
    const long = patched(GREGORIAN.definition, {
      [`${REGIME}/name`]: '😀'.repeat(201),
      '/levels': [],
    })
    expect(errorsOf(long, G)).toEqual([
      { code: 'schema.invalid', path: '/levels' },
      { code: 'schema.invalid', path: '/regimes/0/name' },
    ])
  })

  test('empty mappings and non-object unions', () => {
    const definition = patched(GREGORIAN.definition, {
      [`${REGIME}/templates`]: {},
      [`${REGIME}/alignment/at/anchor`]: 'x',
    })
    expect(errorsOf(definition, G)).toEqual([
      { code: 'schema.invalid', path: '/regimes/0/alignment/at/anchor' },
      { code: 'schema.invalid', path: '/regimes/0/templates' },
    ])
  })

  test('formats', () => {
    const definition = patched(GREGORIAN.definition, {
      '/formats': {
        day: '{day} {month.name} {year}',
        week: '{year}',
        intercalary: { month: '{month.name' },
      },
    })
    expect(errorsOf(definition, G)).toEqual([
      { code: 'format.unknown_token', path: '/formats/intercalary/month' },
      { code: 'format.unknown_level', path: '/formats/week' },
    ])
    expect(errorsOf(patched(definition, { '/formats': { day: '' } }), G)).toEqual([
      { code: 'schema.invalid', path: '/formats/day' },
    ])
    expect(validateCalendar(patched(definition, { '/formats': null }), G)).toBeInstanceOf(
      CompiledCalendar,
    )
  })
})

// --- performance (testing.md §4) -----------------------------------------------------------------

test('compiling a million-year period is fast', () => {
  const definition = patched(GREGORIAN.definition, {
    [`${REGIME}/top/pattern`]: {
      kind: 'rules',
      default: 'year_common',
      rules: [
        { when: { mod: '64', eq: '0' }, template: 'year_leap' },
        {
          when: { any: [{ mod: '15625', eq: '3' }, { not: { mod: '8', eq: '1' } }] },
          template: 'year_leap',
        },
      ],
    },
  })
  const started = performance.now()
  const result = compiled(definition, G)
  const elapsed = performance.now() - started
  expect(defined(result.regimes[0]).period).toBe(1_000_000n)
  expect(elapsed).toBeLessThan(2000)
})
