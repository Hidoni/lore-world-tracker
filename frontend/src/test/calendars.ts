import { absoluteMoments, instantiatePreset, PRESETS } from '@lore/chronology/presets'

import { lenses, type DimensionTime } from '@/core/time'
import { row } from '@/test/fake-vault'
import type { Entity } from '@/data'

/** A dimension of seconds lasting 10^40 of them, with `defaultCalendarId` as its default. */
export function testDimension(defaultCalendarId: string | null = null): DimensionTime {
  return {
    id: 'd1',
    name: 'Aetheria',
    baseUnit: { singular: 'second', plural: 'seconds', abbr: 's' },
    duration: 10n ** 40n,
    defaultCalendarId,
    primeTimelineId: null,
    present: null,
  }
}

/** A calendar entity (domain form) instantiating a preset with one-second base units. */
export function presetCalendar(id: string, presetId: string, revision = 1): Entity {
  const preset = PRESETS.get(presetId)
  if (preset === undefined) throw new Error(`no preset ${presetId}`)
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

/** The display calendars of `testDimension` with these presets (the first is the default). */
export function presetLenses(...presetIds: string[]) {
  const dimension = testDimension(presetIds[0] ?? null)
  return {
    dimension,
    lenses: lenses(
      dimension,
      presetIds.map((presetId) => presetCalendar(presetId, presetId)),
    ),
  }
}

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }

/** A dimension row (wire `ext`) for the fake vault: seconds, `duration`, its default calendar. */
export function dimensionRow(
  id: string,
  name: string,
  defaultCalendar: string | null,
  options: { duration?: bigint; present?: bigint | null } = {},
) {
  const present = options.present ?? null
  return row(id, 'dimension', name, {
    ext: {
      base_unit: SECOND,
      duration: (options.duration ?? 10n ** 40n).toString(),
      default_calendar_id: defaultCalendar,
      present:
        present === null
          ? null
          : { anchor: { kind: 'absolute', t: present.toString() }, precision: 'base' },
      present_t: present === null ? null : present.toString(),
      time_status: 'ok',
      prime_timeline_id: `${id}-prime`,
    },
  })
}

/** A calendar row (wire `ext`) of a dimension, instantiating a preset with one-second units. */
export function calendarRow(id: string, name: string, presetId: string, dimension = 'd1') {
  const preset = PRESETS.get(presetId)
  if (preset === undefined) throw new Error(`no preset ${presetId}`)
  const definition = instantiatePreset(preset, { num: 1n, den: 1n })
  return row(id, 'calendar', name, {
    dimension_id: dimension,
    ext: {
      dimension_id: dimension,
      definition,
      definition_revision: 1,
      resolved_anchors: absoluteMoments(definition),
      compile_status: 'ok',
      compile_errors: [],
    },
  })
}
