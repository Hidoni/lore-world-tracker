import { absoluteMoments, instantiatePreset, PRESETS } from '@lore/chronology/presets'
import { describe, expect, it } from 'vitest'

import type { Entity } from '@/data'

import { ABSOLUTE, compiledCalendar, lenses, type DimensionTime } from './calendars'
import { displayLevel, formatIn, relativeToPresent } from './format'

const DIMENSION: DimensionTime = {
  id: 'd1',
  name: 'Aetheria',
  baseUnit: { singular: 'second', plural: 'seconds', abbr: 's' },
  duration: 10n ** 40n,
  defaultCalendarId: 'c-greg',
  primeTimelineId: null,
  present: null,
}

function calendarEntity(id: string, presetId: string, revision = 1): Entity {
  const preset = PRESETS.get(presetId)
  if (preset === undefined) throw new Error(presetId)
  const definition = instantiatePreset(preset, { num: 1n, den: 1n })
  return {
    id,
    name: preset.name,
    kind: 'calendar',
    deleted_at: null,
    ext: {
      definition,
      definition_revision: revision,
      resolved_anchors: absoluteMoments(definition),
    },
  } as unknown as Entity
}

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
})
