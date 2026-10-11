import { absoluteMoments, instantiatePreset, PRESETS } from '@lore/chronology/presets'

import { lenses, type DimensionTime } from '@/core/time'
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
