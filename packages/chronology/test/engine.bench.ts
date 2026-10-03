// Benchmarks of the engine's hot paths, with their budgets (testing.md §4.1; `npm run bench`). Each
// asserts its budget on the median (p50). The Python twins are in
// backend/tests/chronology/test_benchmarks.py; the tick budget is in ticks.bench.ts.
import fc from 'fast-check'
import { describe, expect, test, type TestContext } from 'vitest'

import {
  add,
  type CompiledCalendar,
  type DateFields,
  diff,
  differenceDuration,
  fromFields,
  fromOrdinal,
  ordinal,
  toFields,
  validateCalendar,
} from '../src/calendar'
import { expand, type RecurrenceContext, seriesBounds } from '../src/recurrence'
import type { RecurrenceRule } from '../src/schema.gen'
import { compiled, load, patched } from './calendars'

const DAY = 86_400n
const BATCH = 1000

const PRESET = load('preset-gregorian')
const GREGORIAN_DOCUMENT = load('gregorian-seconds') // the calendar the budgets were set on
const GREGORIAN = compiled(GREGORIAN_DOCUMENT.definition, GREGORIAN_DOCUMENT.context)
const WEEK = load('gregorian-week')

/** Benchmark `run` (over `items` items) and assert the median per item (`budget` in ms). */
async function measure(
  name: string,
  run: () => void,
  items: number,
  budget: number,
  bench: TestContext['bench'],
): Promise<void> {
  const result = await bench(name, run).run()
  expect(result.latency.p50 / items).toBeLessThan(budget)
}

function moments(count: number, max: bigint, seed: number): bigint[] {
  return fc.sample(fc.bigInt({ min: 0n, max }), { numRuns: count, seed })
}

/** Fields as a user would store them: slot ids for named units, numbers otherwise. */
function asInput(date: DateFields): Record<string, string> {
  const fields: Record<string, string> = {}
  for (const [level, value] of date.levels) fields[level] = value.slotId ?? String(value.n)
  return fields
}

describe('compile', () => {
  test('Gregorian preset: < 20 ms', async ({ bench }) => {
    await measure(
      'compile gregorian',
      () => validateCalendar(PRESET.definition, PRESET.context),
      1,
      20,
      bench,
    )
  })

  test('1,000,000-year period: < 2 s (#10)', async ({ bench }) => {
    const definition = patched(GREGORIAN_DOCUMENT.definition, {
      '/regimes/0/top/pattern': {
        kind: 'rules',
        default: 'year_common',
        rules: [
          { when: { mod: '64', eq: '0' }, template: 'year_leap' },
          { when: { mod: '15625', eq: '3' }, template: 'year_leap' },
        ],
      },
    })
    await measure(
      'compile million-year period',
      () => compiled(definition, GREGORIAN_DOCUMENT.context),
      1,
      2000,
      bench,
    )
  })
})

describe('conversions', () => {
  // #11: ≥ 50,000 conversions/s, i.e. < 20 µs each (years 0 to ~6 million).
  const batch = moments(BATCH, 2n * 10n ** 14n, 1)
  const inputs = batch.map((t) => asInput(toFields(GREGORIAN, t)))

  test('toFields: < 20 µs', async ({ bench }) => {
    await measure(
      'toFields',
      () => {
        batch.forEach((t) => toFields(GREGORIAN, t))
      },
      BATCH,
      0.02,
      bench,
    )
  })

  test('fromFields: < 20 µs', async ({ bench }) => {
    const run = () => {
      inputs.forEach((fields) => fromFields(GREGORIAN, fields, 'second'))
    }
    await measure('fromFields', run, BATCH, 0.02, bench)
  })

  test('ordinal + fromOrdinal: < 100 µs (#12)', async ({ bench }) => {
    const random = moments(BATCH, 10n ** 30n, 3)
    const run = () => {
      for (const t of random) fromOrdinal(GREGORIAN, 'day', ordinal(GREGORIAN, t, 'day').value)
    }
    await measure('ordinal round trip', run, BATCH, 0.1, bench)
  })
})

describe('arithmetic', () => {
  test('diff (years to seconds) and add back over 10^200 s: < 10 ms (#16)', async ({ bench }) => {
    const pairs = fc.sample(
      fc.tuple(fc.bigInt({ min: 0n, max: 10n ** 200n }), fc.bigInt({ min: 0n, max: 10n ** 200n })),
      { numRuns: 30, seed: 4 },
    )
    const run = () => {
      for (const [a, b] of pairs) {
        const found = diff(GREGORIAN, a < b ? a : b, a < b ? b : a, 'year', 'second')
        add(GREGORIAN, a, differenceDuration(found, 'cal'))
      }
    }
    await measure('add/diff far', run, pairs.length, 10, bench)
  })
})

describe('recurrence', () => {
  const rule = (members: Record<string, unknown>): RecurrenceRule =>
    ({
      kind: 'calendar',
      calendar_id: 'cal',
      limit: { kind: 'never' },
      ...members,
    }) as RecurrenceRule
  const start = (calendar: CompiledCalendar) =>
    fromFields(calendar, { year: '2024', month: 'feb', day: '29', hour: '9' }, 'hour')
  const context = (calendar: CompiledCalendar, duration: unknown): RecurrenceContext => ({
    seriesStart: start(calendar),
    end: { kind: 'instant' },
    dimensionDuration: BigInt(duration as string),
    calendar,
    resolved: {},
  })

  test('expand a window 10^90 years away: < 50 ms (#19)', async ({ bench }) => {
    const monthly = rule({ freq: { level: 'month' }, time: { fields: { hour: '9' } } })
    const ctx = context(GREGORIAN, GREGORIAN.context.dimension_duration)
    const far = ctx.seriesStart + 10n ** 90n * 365n * DAY
    expect(expand(monthly, ctx, [far, far + 400n * DAY], 100).items.length).toBeGreaterThan(11)
    await measure(
      'expand far window',
      () => expand(monthly, ctx, [far, far + 400n * DAY]),
      1,
      50,
      bench,
    )
  })

  test('series bounds of count = 10^12, fresh calendar: < 100 ms (#21)', async ({ bench }) => {
    const yearly = rule({
      freq: { level: 'year' },
      limit: { kind: 'count', count: '1000000000000' },
    })
    const run = () => {
      const calendar = compiled(WEEK.definition, WEEK.context) // no cached counters
      seriesBounds(yearly, context(calendar, calendar.context.dimension_duration))
    }
    await measure('series bounds far count', run, 1, 100, bench)
  })
})
