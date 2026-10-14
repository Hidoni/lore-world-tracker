import { add, fromFields } from '@lore/chronology'
import { describe, expect, it } from 'vitest'

import { presetCalendar, testDimension } from '@/test/calendars'

import { lenses } from './calendars'
import { elapsedIn, relativeTo } from './format'

const DAY = 86_400n
/** 24 December AD 2023 in the Gregorian preset (seconds since 1 January AD 1). */
const DEC_2023 = 63_839_000_000n

function setup(presetId: string) {
  const dimension = testDimension(presetId)
  const all = lenses(dimension, [presetCalendar(presetId, presetId)])
  const lens = all[0]
  const absolute = all[all.length - 1]
  if (lens?.calendar == null || absolute === undefined) throw new Error('no calendar')
  return { dimension, lens, calendar: lens.calendar, absolute }
}

const years = (n: string, months = '0') => ({
  kind: 'calendar' as const,
  calendar_id: 'c',
  amounts: { year: n, month: months },
  sign: 1 as const,
})

describe('elapsed time', () => {
  const greg = setup('gregorian')

  it('shows the two coarsest units', () => {
    const later = add(greg.calendar, DEC_2023, years('34', '2'))
    expect(elapsedIn(greg.lens, DEC_2023, later, greg.dimension)).toEqual({
      text: '34 years, 2 months',
      sign: 1,
    })
    expect(elapsedIn(greg.lens, later, DEC_2023, greg.dimension)?.sign).toBe(-1)
    expect(elapsedIn(greg.lens, DEC_2023, DEC_2023 + 3n * DAY + 7n, greg.dimension)?.text).toBe(
      '3 days',
    )
    expect(elapsedIn(greg.lens, DEC_2023, DEC_2023 + 40n, greg.dimension)?.text).toBe('40 seconds')
  })

  it('counts a leap year as one year', () => {
    // 28 February 2024 to 28 February 2025: one year of 366 days.
    const feb28 = DEC_2023 + 66n * DAY
    const next = add(greg.calendar, feb28, years('1'))
    expect(next - feb28).toBe(366n * DAY)
    expect(elapsedIn(greg.lens, feb28, next, greg.dimension)?.text).toBe('1 year')
    expect(elapsedIn(greg.lens, feb28, feb28 + 2n * DAY, greg.dimension)?.text).toBe('2 days')
  })

  it('counts years of alternating lengths as years', () => {
    const alt = setup('alternating-years')
    const one = fromFields(alt.calendar, { year: '1' }, 'year')
    const two = fromFields(alt.calendar, { year: '2' }, 'year')
    const three = fromFields(alt.calendar, { year: '3' }, 'year')
    expect(two - one).not.toBe(three - two)
    expect(elapsedIn(alt.lens, one, three, alt.dimension)?.text).toBe('2 years')
    expect(elapsedIn(alt.lens, one, two, alt.dimension)?.text).toBe('1 year')
  })

  it('shows huge spans in scientific notation', () => {
    const far = add(greg.calendar, DEC_2023, years('3200000000'))
    expect(elapsedIn(greg.lens, DEC_2023, far, greg.dimension)?.text).toBe('3.2 × 10^9 years')
    const thousands = add(greg.calendar, DEC_2023, years('4500', '3'))
    expect(elapsedIn(greg.lens, DEC_2023, thousands, greg.dimension)?.text).toBe('4,500 years')
  })

  it('says how long ago or from now, also in base units', () => {
    const later = add(greg.calendar, DEC_2023, years('2'))
    expect(relativeTo(greg.lens, DEC_2023, later, greg.dimension)).toBe('2 years ago')
    expect(relativeTo(greg.lens, later, DEC_2023, greg.dimension)).toBe('2 years from now')
    expect(relativeTo(greg.lens, later, later, greg.dimension)).toBeNull()
    expect(relativeTo(greg.absolute, 10n, 70n, greg.dimension)).toBe('60 seconds ago')
  })
})
