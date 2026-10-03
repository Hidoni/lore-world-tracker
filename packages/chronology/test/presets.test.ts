// Preset calendars (chronology-engine.md §13), mirroring the Python engine's
// backend/tests/chronology/test_presets.py. Vectors: cases/presets/.
import { describe, expect, test } from 'vitest'

import { compileCalendar, CompiledCalendar } from '../src/calendar'
import { type BigRational, rational } from '../src/numbers'
import { PRESETS } from '../src/preset-library'
import { absoluteMoments, instantiatePreset, PresetError } from '../src/presets'
import type { Preset } from '../src/schema.gen'
import { load, patched } from './calendars'

const REQUIRED = [
  'alternating-years',
  'gregorian',
  'julian',
  'julian-gregorian',
  'lunisolar-metonic',
  'mayan',
  'shire-reckoning',
  'simple-360',
]
const BASE_UNITS = [
  rational(1n, 1000n),
  rational(1n),
  rational(60n),
  rational(3600n),
  rational(86400n),
]

function preset(id: string): Preset {
  const found = PRESETS.get(id)
  if (found === undefined) throw new Error(`no preset ${id}`)
  return found
}

function compilePreset(source: Preset, seconds: BigRational, origin = 0n): CompiledCalendar {
  const definition = instantiatePreset(source, seconds, { origin })
  const context = {
    base_unit: { singular: 'unit', plural: 'units', abbr: 'u' },
    dimension_duration: (10n ** 120n).toString(),
    resolved: absoluteMoments(definition),
  }
  const result = compileCalendar(definition, context)
  if (!(result instanceof CompiledCalendar)) throw new Error(JSON.stringify(result))
  return result
}

test('the required presets are bundled', () => {
  expect([...PRESETS.keys()]).toEqual(REQUIRED)
  for (const [id, found] of PRESETS) {
    expect(found.id).toBe(id)
    const level0 = found.definition.levels[0]
    expect(level0.id).toBe('second')
    for (const regime of found.definition.regimes) {
      expect(regime.templates[level0.default_template ?? '']).toEqual({
        level: 'second',
        uniform: { count: '1' },
      })
    }
  }
})

describe.each(REQUIRED)('%s', (id) => {
  test.each(BASE_UNITS.map((unit) => [`${unit.num}/${unit.den} s`, unit] as const))(
    'compiles for a base unit of %s',
    (_, unit) => {
      expect(compilePreset(preset(id), unit, 10n ** 12n)).toBeInstanceOf(CompiledCalendar)
    },
  )

  test('requires covers the absolute anchors', () => {
    const moments = Object.values(absoluteMoments(instantiatePreset(preset(id), rational(1n))))
    const latest = moments.reduce((most, t) => (BigInt(t) > BigInt(most) ? t : most))
    expect(preset(id).requires.duration_seconds).toBe(latest)
  })

  test('the conformance calendar file matches the preset', () => {
    const document = load(`preset-${id}`) as {
      definition: unknown
      context: { resolved: unknown }
    }
    const definition = instantiatePreset(preset(id), rational(1n), { origin: 10n ** 14n })
    expect(definition).toStrictEqual(document.definition)
    expect(absoluteMoments(definition)).toStrictEqual(document.context.resolved)
  })
})

test('dropping a level a date needs is incompatible', () => {
  const source = patched(preset('simple-360'), {
    '/definition/regimes/0/alignment/fields/hour': '6',
  })
  expect(compilePreset(source, rational(1n))).toBeInstanceOf(CompiledCalendar)
  expect(() => instantiatePreset(source, rational(86400n))).toThrow(PresetError)
})

test('a base unit must be positive', () => {
  expect(() => instantiatePreset(preset('julian'), rational(-1n))).toThrow(PresetError)
})

test('instantiation leaves the bundled preset untouched', () => {
  const before = structuredClone(preset('gregorian'))
  instantiatePreset(preset('gregorian'), rational(86400n), { origin: 5n })
  expect(preset('gregorian')).toStrictEqual(before)
})

test('dropped levels leave dates and formats', () => {
  const source = patched(preset('simple-360'), {
    '/definition/regimes/0/alignment/fields/hour': '0', // the first hour: droppable
    '/definition/formats/intercalary': { day: '{day} {hour}', month: '{month}' },
  })
  const definition = instantiatePreset(source, rational(86400n))
  expect(definition.levels.map((level) => level.id)).toEqual(['day', 'month', 'year'])
  expect(definition.regimes[0].alignment.fields).toEqual({ year: '1', month: '1', day: '1' })
  expect(definition.formats).toEqual({
    year: '{year}',
    month: '{year}-{month:pad2}',
    day: '{year}-{month:pad2}-{day:pad2}',
    intercalary: { month: '{month}' },
  })
})

test('a cycle on a dropped level is incompatible', () => {
  // the Shire week counts days: a base unit of a week would drop them
  expect(() => instantiatePreset(preset('shire-reckoning'), rational(7n * 86400n))).toThrow(
    PresetError,
  )
})

test('non-absolute anchors and missing formats', () => {
  const definition = preset('simple-360').definition
  const local = {
    anchor: { kind: 'local', fields: { year: '2', month: '1', day: '1', hour: '0' } },
    precision: 'hour',
  }
  const relative = {
    anchor: {
      kind: 'relative',
      ref: { type: 'event', id: 'e', slot: 'start' },
      offset: { kind: 'base', units: '0' },
    },
    precision: 'base',
  }
  const source = patched(preset('simple-360'), {
    '/definition/formats': undefined,
    '/definition/overlays': [
      {
        id: 'moon',
        name: 'Moon',
        period: { num: '86400', den: '1' },
        epoch: local,
        phases: [{ name: 'New', from: { num: '0', den: '1' } }],
      },
    ],
    '/definition/eras': [
      { id: 'before', name: 'Before', abbr: 'B', numbering: { direction: 'backward', first: '1' } },
      {
        id: 'after',
        name: 'After',
        abbr: 'A',
        start: relative,
        numbering: { direction: 'forward', first: '1' },
      },
    ],
  })
  const found = instantiatePreset(source, rational(86400n))
  expect(found.formats).toBeUndefined()
  expect(found.overlays?.[0]?.epoch).toEqual({
    anchor: { kind: 'local', fields: { year: '2', month: '1', day: '1' } },
    precision: 'day',
  })
  expect(found.overlays?.[0]?.period).toEqual({ num: '1', den: '1' })
  expect(found.eras?.[1]?.start).toEqual(relative)
  expect(definition.levels).toHaveLength(6) // the bundled preset is untouched
})

test('a cycle on a dropped level is refused', () => {
  const source = patched(preset('simple-360'), {
    '/definition/regimes/0/cycles': [
      {
        id: 'watch',
        level: 'hour',
        length: 4,
        anchor: { fields: { year: '1', month: '1', day: '1', hour: '0' } },
      },
    ],
  })
  expect(() => instantiatePreset(source, rational(86400n))).toThrow(PresetError)
  expect(instantiatePreset(source, rational(3600n)).levels[0].id).toBe('hour')
})
