import {
  formatDate,
  fromFields,
  nextOccurrences,
  type RecurrenceRule,
  validateRule,
} from '@lore/chronology'
import { describe, expect, it } from 'vitest'

import { compiledCalendar } from '@/core/time'
import { presetCalendar, testDimension } from '@/test/calendars'

import {
  availablePresets,
  detectPreset,
  presetRule,
  summarize,
  type PresetId,
  type RuleScope,
} from './rule-model'

const calendar = compiledCalendar(presetCalendar('c-greg', 'gregorian'), testDimension())
if (calendar === null) throw new Error('gregorian')
const GREGORIAN = calendar
// Tuesday 10 March 2026 at 09:30.
const START = fromFields(
  GREGORIAN,
  { year: '2026', month: 'mar', day: '10', hour: '9', minute: '30' },
  'minute',
)
const scope: RuleScope = {
  calendarId: 'c-greg',
  calendar: GREGORIAN,
  start: START,
  baseUnit: { singular: 'second', plural: 'seconds' },
}
const ctx = {
  seriesStart: START,
  end: { kind: 'instant' as const },
  dimensionDuration: 10n ** 40n,
  calendar: GREGORIAN,
}

function next(preset: PresetId, options = {}): string[] {
  const rule = presetRule(preset, scope, options)
  if (rule === null) throw new Error(preset)
  expect(validateRule(rule, ctx)).toEqual([])
  return nextOccurrences(rule, ctx, START - 1n, 3).map((item) =>
    formatDate(GREGORIAN, item.start, 'minute'),
  )
}

describe('recurrence presets', () => {
  it('offers every preset for a calendar with months and weeks', () => {
    expect(availablePresets(scope)).toEqual([
      'yearly',
      'monthly',
      'nth_weekday',
      'weekly',
      'interval',
      'custom',
    ])
    expect(availablePresets({ ...scope, calendar: null })).toEqual(['interval', 'custom'])
  })

  it('builds valid rules from the series start, and recognizes them', () => {
    expect(next('yearly')).toEqual([
      formatDate(GREGORIAN, START, 'minute'),
      formatDate(
        GREGORIAN,
        fromFields(
          GREGORIAN,
          { year: '2027', month: 'mar', day: '10', hour: '9', minute: '30' },
          'minute',
        ),
        'minute',
      ),
      formatDate(
        GREGORIAN,
        fromFields(
          GREGORIAN,
          { year: '2028', month: 'mar', day: '10', hour: '9', minute: '30' },
          'minute',
        ),
        'minute',
      ),
    ])
    expect(presetRule('monthly', scope)).toMatchObject({
      freq: { level: 'month' },
      select: { path: [{ level: 'day', values: ['10'] }] },
    })
    expect(next('monthly')).toHaveLength(3)
    // 10 March 2026 is the second Tuesday.
    expect(presetRule('nth_weekday', scope)).toMatchObject({
      select: { path: [{ level: 'day', cycle: { id: 'week', values: ['tue'], nth: ['2'] } }] },
    })
    expect(next('nth_weekday')).toHaveLength(3)
    expect(presetRule('weekly', scope, { weekdays: ['tue', 'fri'] })).toMatchObject({
      freq: { cycle: 'week' },
      select: { path: [{ level: 'day', cycle: { id: 'week', values: ['tue', 'fri'] } }] },
    })
    expect(next('weekly', { weekdays: ['tue', 'fri'] })).toHaveLength(3)
    for (const preset of ['yearly', 'monthly', 'nth_weekday', 'weekly', 'interval'] as const) {
      const rule = presetRule(preset, scope, { every: preset === 'interval' ? '600' : '2' })
      if (rule === null) throw new Error(preset)
      expect(detectPreset(rule, scope)).toBe(preset)
    }
    // Stored rules spell out the defaults.
    const stored = {
      ...presetRule('yearly', scope),
      schema_version: 1,
      interval: '1',
      filters: [],
      select: null,
      missing: 'skip',
      time: null,
      exclusions: [],
    } as RecurrenceRule
    expect(detectPreset(stored, scope)).toBe('yearly')
  })

  it('summarizes rules in words', () => {
    const say = (preset: PresetId, options = {}) => {
      const rule = presetRule(preset, scope, options)
      if (rule === null) throw new Error(preset)
      return summarize(rule, scope)
    }
    expect(say('yearly')).toBe('Every year on day 10 of March.')
    expect(say('yearly', { every: '7', limit: { kind: 'count', count: '3' } })).toBe(
      'Every 7 years on day 10 of March, 3 times.',
    )
    expect(say('monthly')).toBe('Every month on day 10.')
    expect(say('nth_weekday')).toBe('Every month on the second Tuesday.')
    expect(say('weekly', { weekdays: ['tue', 'fri'] })).toBe('Every week on Tuesday and Friday.')
    expect(say('interval', { every: '3600' })).toBe('Every 3,600 seconds.')
    expect(
      summarize(
        {
          kind: 'calendar',
          calendar_id: 'c-greg',
          freq: { level: 'year' },
          filters: [{ mod: '2', eq: '1' }],
          select: {
            path: [
              { level: 'month', values: ['jun'] },
              { level: 'day', values: ['-1'] },
            ],
          },
          time: { fields: { hour: '9' } },
          limit: {
            kind: 'until',
            until: { anchor: { kind: 'absolute', t: '0' }, precision: 'base' },
          },
          exclusions: [
            {
              from: { anchor: { kind: 'absolute', t: '0' }, precision: 'base' },
              to: { anchor: { kind: 'absolute', t: '1' }, precision: 'base' },
            },
          ],
        },
        scope,
        { until: 'the Fall' },
      ),
    ).toBe(
      'Every year on the last day of June at hour 9, odd years only, until the Fall, except one excluded range.',
    )
  })
})
