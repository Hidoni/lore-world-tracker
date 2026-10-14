import { useMemo } from 'react'

import { formatIn, POSSIBLE_NOTE, useTimeContext, type TimeContext } from '@/core/time'
import type { Genealogy } from '@/data'

type Person = Genealogy['people'][number]

/** How a person shows at the time cursor (`recorded`: a lifespan, but no cursor). */
export type LifeState = 'unknown' | 'recorded' | 'alive' | 'possible' | 'unborn' | 'deceased'

export interface PersonLife {
  /** "1170 – 1250", "1170 –" (still alive), "… – 1250"; `null` without a lifespan. */
  lifespan: string | null
  state: LifeState
  /** Why the person is muted, or what is unknown. */
  note: string | null
}

/** A person's life as the family tree shows it: their lifespan, and their state at the cursor. */
export function describeLife(person: Person, cursor: bigint | null, date: (t: bigint) => string) {
  const { from_t: from, to_t: to } = person
  const lifespan =
    from === null && to === null
      ? null
      : `${from === null ? '…' : date(from)} – ${to === null ? '' : date(to)}`.trim()
  const life = (state: LifeState, note: string | null): PersonLife => ({ lifespan, state, note })
  switch (person.existence) {
    case 'exists':
      return life('alive', null)
    case 'possible':
      return life('possible', POSSIBLE_NOTE)
    case 'not_exists':
      if (cursor !== null && from !== null && cursor < from) return life('unborn', 'Not yet born')
      if (cursor !== null && to !== null && cursor >= to) return life('deceased', 'Died')
      return life('deceased', 'Not alive then')
    default:
      return lifespan === null ? life('unknown', 'Lifespan unknown') : life('recorded', null)
  }
}

function dateIn(context: TimeContext) {
  const { lens, lenses, dimension } = context
  return (t: bigint): string =>
    lens === null || dimension === null
      ? t.toString()
      : (formatIn(lens, { t, precision: 'base' }, dimension, lenses) ?? t.toString())
}

/** Each person's life (by id), in the time context's lens and at its cursor. */
export function usePeopleLives(vault: string, family: Genealogy | undefined) {
  const context = useTimeContext(vault)
  const cursor = context.moment
  const date = dateIn(context)
  return useMemo(
    () =>
      new Map(
        (family?.people ?? []).map((person) => [person.id, describeLife(person, cursor, date)]),
      ),
    // `date` changes with the lens, which the context's identity follows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [family, cursor, context.lens, context.dimension],
  )
}
