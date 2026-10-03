// Formatting (chronology-engine.md §3.11, §10), mirroring the Python engine's
// backend/tests/chronology/test_calendar_formatting.py. Vectors: cases/formatting/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  type CompiledCalendar,
  formatAbsolute,
  formatDate,
  formatSpan,
  PatternError,
  parsePattern,
} from '../src/calendar'
import { token } from '../src/calendar/formats'
import { compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261003 }

const LEAP_DAY_2024 = 100_000_762_523_200n // Thursday 29 February 2024 12:00 (cases/cycles/gregorian-week)
const MARCH_1_2024 = LEAP_DAY_2024 + 12n * 3600n
const OVERLITHE_4 = 10_001_278n // cases/cycles/shire-week::to-fields-overlithe
const DASH = ' – ' // the default range separator

function withFormats(name: string, formats: unknown): CompiledCalendar {
  const { definition, context } = load(name)
  return compiled(patched(definition, { '/formats': formats }), context)
}

const GREGORIAN = (() => {
  const { definition, context } = load('gregorian-seconds')
  return compiled(definition, context)
})()

describe('examples', () => {
  test('era tokens without eras', () => {
    const cal = withFormats('gregorian-week', {
      day: '{cycle.week}, {day} {month.name} {era_year} {era}{era.name}',
    })
    expect(formatDate(cal, LEAP_DAY_2024, 'day')).toBe('Thursday, 29 February 2024')
  })

  test('an excluded cycle renders empty', () => {
    const cal = withFormats('shire-week', { intercalary: { day: '[{cycle.week}] {month.name}' } })
    expect(formatDate(cal, OVERLITHE_4, 'day')).toBe('[] Overlithe')
  })

  test('a span with interleaved tokens is not collapsed', () => {
    const cal = withFormats('gregorian-week', { day: '{day} {year} {month.name}' })
    const start = { t: LEAP_DAY_2024, precision: 'day' }
    const end = { t: MARCH_1_2024, precision: 'day' }
    expect(formatSpan(cal, start, end)).toBe('29 2024 February – 1 2024 March')
  })

  test('parse', () => {
    expect(parsePattern('{{{day:pad2}}} {era.name}')).toEqual([
      '{',
      token('level', 'day', null, 'pad2'),
      '} ',
      token('era', null, 'name'),
    ])
    expect(() => parsePattern('{day.name:pad2}')).toThrow(PatternError)
    expect(() => parsePattern('{year.name}')).toThrow(PatternError)
  })

  test('the absolute calendar', () => {
    const unit = { singular: 'second', plural: 'seconds', abbr: 's' }
    expect(formatAbsolute(1234n, unit)).toBe('t = 1,234 s')
    expect(formatAbsolute(1234n, unit, { digit_group: '' }, { approximate: true })).toBe(
      'c. t = 1234 s',
    )
  })
})

test('a span shortens at most one end', () => {
  const precisions = ['second', 'minute', 'hour', 'day', 'month', 'year', 'base']
  fc.assert(
    fc.property(
      fc.bigInt({ min: 0n, max: 10n ** 16n }),
      fc.bigInt({ min: 0n, max: 10n ** 10n }),
      fc.constantFrom(...precisions),
      (t, length, precision) => {
        const first = formatDate(GREGORIAN, t, precision)
        const last = formatDate(GREGORIAN, t + length, precision)
        const text = formatSpan(GREGORIAN, { t, precision }, { t: t + length, precision })
        const shortened =
          text === first || text.startsWith(`${first}${DASH}`) || text.endsWith(`${DASH}${last}`)
        expect(shortened).toBe(true)
        expect(text === first).toBe(first === last)
      },
    ),
    params,
  )
})
