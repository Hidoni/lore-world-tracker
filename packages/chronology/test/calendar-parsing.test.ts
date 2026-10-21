// Parsing typed dates (chronology-engine.md §10.1), mirroring the Python engine's
// backend/tests/chronology/test_calendar_parsing.py. Vectors: cases/parsing/.
import { readdirSync } from 'node:fs'

import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  type CompiledCalendar,
  DateError,
  formatDate,
  parseDate,
  parsedDateToJson,
  unitBounds,
} from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import { compiled, load } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261021 }

const NAMES = readdirSync(
  new URL('../../../spec/chronology/conformance/calendars/', import.meta.url),
)
  .filter((file) => file.endsWith('.json'))
  .map((file) => file.slice(0, -'.json'.length))
  .sort()
const CALENDARS = new Map<string, CompiledCalendar>(
  NAMES.map((name) => {
    const { definition, context } = load(name)
    return [name, compiled(definition, context)]
  }),
)
const GREGORIAN = defined(CALENDARS.get('gregorian-seconds'))
const Y2K = 100_000_000_000_000n // 1 January 2000 00:00:00 (cases/conversions/gregorian-seconds)

describe('parseDate', () => {
  test('formatted text reads back as the same text', () => {
    // The unit containing the moment, or another one written the same way (a text can name
    // several units, like a reform year). Custom patterns can show finer values (`{base}`,
    // overlays) that the parsed unit start lacks.
    fc.assert(
      fc.property(
        fc.constantFrom(...NAMES),
        fc.bigInt(-(10n ** 12n), 10n ** 12n),
        fc.integer({ min: 0, max: 6 }),
        (name, offset, level) => {
          const calendar = defined(CALENDARS.get(name))
          const precisions = [...calendar.levels, 'base']
          const precision = defined(precisions[Math.min(level, precisions.length - 1)])
          const dated = /^(gregorian|julian|japanese)/.test(name)
          const t = dated ? (Y2K + offset < 0n ? 0n : Y2K + offset) : offset < 0n ? -offset : offset
          let text: string
          try {
            text = formatDate(calendar, t, precision)
          } catch (error) {
            if (error instanceof DateError) return
            throw error
          }
          if (text.includes('×')) return // scientific notation is not exact (§10.1)
          const found = parseDate(calendar, text)
          if (found.precision === 'base') {
            expect(found.t).toBe(t)
          } else if (formatDate(calendar, found.t, found.precision) !== text) {
            const bounds = unitBounds(calendar, found.t, found.precision)
            expect(bounds.start <= t && t < bounds.end).toBe(true)
          }
        },
      ),
      params,
    )
  })

  test('the Gregorian round trip is exact', () => {
    fc.assert(
      fc.property(
        fc.bigInt(-(10n ** 13n), 10n ** 13n),
        fc.constantFrom('year', 'month', 'day', 'hour', 'minute'),
        (offset, precision) => {
          const t = Y2K + offset
          const found = parseDate(GREGORIAN, formatDate(GREGORIAN, t, precision))
          expect([found.precision, found.t]).toEqual([
            precision,
            unitBounds(GREGORIAN, t, precision).start,
          ])
        },
      ),
      params,
    )
  })

  test('result shape', () => {
    const found = parseDate(GREGORIAN, 'c.  15 Mar 2024, 14:30')
    expect(parsedDateToJson(found)).toEqual({
      fields: { year: '2024', month: 'mar', day: '15', hour: '14', minute: '30' },
      era: null,
      precision: 'minute',
      approximate: true,
      t: unitBounds(GREGORIAN, found.t, 'minute').start.toString(),
    })
    expect(formatDate(GREGORIAN, found.t, 'minute')).toBe('15 March 2024, 14:30')
  })

  test.each(['', 'c.', '15 Mar', 'March 2024 15', '15 March 2024,', '²⁰²⁴'])(
    'no date: %j',
    (text) => {
      expect(() => parseDate(GREGORIAN, text)).toThrow(
        expect.objectContaining({ code: 'invalid_date' }),
      )
    },
  )
})
