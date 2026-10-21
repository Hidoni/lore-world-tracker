import { occurrence } from '@lore/chronology'

import { formatIn, useDisplayLens } from '@/core/time'
import { useEntity, useOccurrences } from '@/data'

import { eventTime } from '../event-time'
import { ordinal } from './occurrence-header'
import { widened } from './rule-model'

/**
 * How an anchor names an occurrence of a series (recurrence.md §3): "the 3rd occurrence of", the
 * number being the server's (keys count skipped periods, so `k` isn't the number); "the
 * occurrence on <date> of" while it is unknown, "an occurrence of" when the key has none.
 */
export function OccurrenceRefLabel({
  vault,
  seriesId,
  occurrenceKey,
}: {
  vault: string
  seriesId: string
  occurrenceKey: string
}) {
  const series = useEntity(vault, seriesId)
  const time = series.data === undefined ? null : eventTime(series.data)
  const { dimension, lens, lenses } = useDisplayLens(vault, series.data?.dimension_id ?? null)
  let start: bigint | null = null
  const rule = time?.recurrence ?? null
  if (rule !== null && time?.startT != null && dimension !== null) {
    const calendar =
      rule.kind !== 'interval'
        ? (lenses.find((candidate) => candidate.id === rule.calendar_id)?.calendar ?? null)
        : null
    try {
      start = occurrence(
        widened(rule),
        {
          seriesStart: time.startT,
          end: time.end ?? { kind: 'instant' },
          dimensionDuration: dimension.duration,
          calendar,
        },
        occurrenceKey,
      ).start
    } catch {
      start = null
    }
  }
  const list = useOccurrences(
    vault,
    seriesId,
    start === null ? null : { from: start, to: start + 1n },
    { includeCancelled: true, limit: 10 },
  )
  const found = list.data?.items.find((item) => item.key === occurrenceKey)
  if (found?.number != null) return <>the {ordinal(found.number)} occurrence of</>
  if (start !== null && dimension !== null && lens !== null) {
    const precision = time?.start?.precision ?? 'base'
    const date = formatIn(lens, { t: start, precision }, dimension, lenses)
    if (date !== null) return <>the occurrence on {date} of</>
  }
  return <>an occurrence of</>
}
