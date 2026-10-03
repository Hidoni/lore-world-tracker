// Acceptance (#28): ticks for any viewport take < 2 ms for typical calendars (`npm run bench`).
import { describe, expect, test } from 'vitest'

import { fromFields } from '../src/calendar'
import { ticks, viewport } from '../src/viewport'
import { compiled, load } from './calendars'

const DAY = 86400n

function calendarOf(name: string) {
  const { definition, context } = load(name)
  return compiled(definition, context)
}

const gregorian = calendarOf('preset-gregorian')
const mayan = calendarOf('preset-mayan')
const shire = calendarOf('preset-shire-reckoning')
const now = fromFields(gregorian, { year: '2024', month: 'mar', day: '15' }, 'day')

/** Spans from a minute to far beyond recorded history. */
const SPANS = [60n, DAY, 40n * DAY, 400n * DAY, 400n * 365n * DAY, 10n ** 20n, 10n ** 60n]

for (const [name, calendar, start] of [
  ['gregorian', gregorian, now],
  ['mayan', mayan, BigInt(mayan.context.dimension_duration) / 3n],
  ['shire', shire, BigInt(shire.context.dimension_duration) / 3n],
] as const) {
  describe(name, () => {
    test.for(SPANS)('span %s', async (span, { bench }) => {
      const result = await bench(`${name} ${span}`, () => {
        ticks(calendar, viewport(start, span, 1600))
      }).run()
      expect(result.latency.p50).toBeLessThan(2) // ms
    })
  })
}
