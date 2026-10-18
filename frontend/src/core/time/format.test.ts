import type { TimePoint } from '@lore/chronology'
import { describe, expect, it } from 'vitest'

import { presetCalendar, testDimension } from '@/test/calendars'

import { ABSOLUTE, compiledCalendar, lenses } from './calendars'
import { displayLevel, formatIn, formatSpanIn, relativeToPresent } from './format'
import { momentOf, pointMoment } from './point-moment'

const DIMENSION = testDimension('c-greg')
const calendarEntity = presetCalendar

const DEC_2023 = 63_839_000_000n

describe('display calendars', () => {
  const all = lenses(DIMENSION, [
    calendarEntity('c-360', 'simple-360'),
    calendarEntity('c-greg', 'gregorian'),
  ])
  const [gregorian, simple] = all

  it('orders the default first, the others by name, then Absolute', () => {
    expect(all.map((lens) => lens.id)).toEqual(['c-greg', 'c-360', ABSOLUTE])
  })

  it('caches compiled calendars by id, revision and anchors', () => {
    const entity = calendarEntity('c-greg', 'gregorian')
    expect(compiledCalendar(entity, DIMENSION)).toBe(gregorian?.calendar)
    expect(compiledCalendar(calendarEntity('c-greg', 'gregorian', 2), DIMENSION)).not.toBe(
      gregorian?.calendar,
    )
  })

  it('shows a precision the calendar lacks at the coarsest level that fits its extent', () => {
    if (gregorian === undefined || simple === undefined) throw new Error('lenses')
    const month = {
      t: DEC_2023,
      precision: 'season',
      extent: { lo: DEC_2023, hi: DEC_2023 + 40n * 86_400n },
    }
    expect(displayLevel(gregorian, month, all)).toBe('month')
    expect(formatIn(gregorian, month, DIMENSION, all)).toBe('December AD 2023')
    expect(displayLevel(simple, { t: DEC_2023, precision: 'base' }, all)).toBe('base')
    expect(formatIn(simple, { t: DEC_2023, precision: 'nonsense' }, DIMENSION, all)).toBe(
      formatIn(simple, { t: DEC_2023, precision: 'base' }, DIMENSION, all),
    )
  })

  it('says how far a moment is from the present', () => {
    if (gregorian === undefined) throw new Error('lenses')
    const year = 366n * 86_400n
    expect(relativeToPresent(gregorian, DEC_2023, DEC_2023 + 2n * year)).toBe(
      '2 years before present',
    )
    expect(relativeToPresent(gregorian, DEC_2023 + 2n * year, DEC_2023)).toBe(
      '2 years after present',
    )
    expect(relativeToPresent(gregorian, DEC_2023, DEC_2023 + 86_400n)).toBeNull()
    expect(relativeToPresent(gregorian, DEC_2023, null)).toBeNull()
  })

  it('shows an uncertainty range, after its best estimate when that isn’t the earliest', () => {
    if (gregorian === undefined) throw new Error('lenses')
    const year = (n: number): TimePoint => ({
      anchor: { kind: 'calendar', calendar_id: 'c-greg', fields: { year: String(n) } },
      precision: 'year',
    })
    const ranged = (estimate: number): TimePoint => ({
      ...year(estimate),
      range: { earliest: year(1020), latest: year(1025) },
    })
    const at = (point: TimePoint) => {
      const t = pointMoment(point, all)
      if (t === null) throw new Error('no moment')
      return momentOf(t, point, all)
    }
    const earliest = at(ranged(1020))
    if (earliest === null) throw new Error('no moment')
    expect(earliest.range?.latest.t).toBe(pointMoment(year(1025), all))
    expect(formatIn(gregorian, earliest, DIMENSION, all)).toBe('between AD 1020 and 1025')
    const estimate = at(ranged(1022))
    if (estimate === null) throw new Error('no moment')
    expect(formatIn(gregorian, estimate, DIMENSION, all)).toBe('AD 1022 (between AD 1020 and 1025)')
    const end = at(year(1030))
    expect(formatSpanIn(gregorian, estimate, end, DIMENSION, all)).toBe(
      'AD 1022 (between AD 1020 and 1025) – AD 1030',
    )
    // A relative end resolves on the server: the moment shows as its estimate.
    const relative: TimePoint = {
      ...year(1022),
      range: {
        earliest: year(1020),
        latest: {
          anchor: {
            kind: 'relative',
            ref: { type: 'event', id: 'e1', slot: 'start' },
            offset: { kind: 'base', units: '0' },
          },
          precision: 'default',
        },
      },
    }
    const shown = at(relative)
    if (shown === null) throw new Error('no moment')
    expect(formatIn(gregorian, shown, DIMENSION, all)).toBe('AD 1022')
  })
})
