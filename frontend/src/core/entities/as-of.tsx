import type { AsOfField } from '@/core/fields'
import { cursorLabel, formatIn, useEntityAsOf, useTimeContext } from '@/core/time'
import { useEntityState, useFacts, type Entity, type EntityState, type Fact } from '@/data'

const EXISTS = 'core.exists'

/** How a kind says it doesn't exist yet, and no longer (time-model.md §10.4). */
const PHRASES: Record<string, { before: string; after: string }> = {
  character: { before: 'Not yet born', after: 'Died' },
  group: { before: 'Not yet founded', after: 'Dissolved' },
  location: { before: 'Not yet founded', after: 'Destroyed' },
  species: { before: 'Not yet emerged', after: 'Extinct' },
  language: { before: 'Not yet emerged', after: 'Extinct' },
}
const DEFAULT_PHRASES = { before: 'Doesn’t exist yet', after: 'No longer exists' }

export interface EntityTime {
  /** The state at the cursor (`undefined`: all time, another dimension, or loading). */
  state: EntityState | undefined
  /** The entity's facts in the cursor's timeline. */
  facts: readonly Fact[]
  /** Temporal fields at the cursor, for the fields panel. */
  fields: Record<string, AsOfField> | undefined
}

/** The entity at the time cursor (time-model.md §10.5): its state and fact history. */
export function useEntityTime(vault: string, entity: Entity): EntityTime {
  const asOf = useEntityAsOf(vault, entity.id)
  const state = useEntityState(vault, entity.id, asOf)
  const facts = useFacts(vault, entity.id, asOf === undefined ? {} : { timeline: asOf.timeline }, {
    enabled: asOf !== undefined,
  })
  const items = asOf === undefined ? [] : (facts.data?.items ?? [])
  const found = asOf === undefined ? undefined : state.data
  if (found === undefined) return { state: undefined, facts: items, fields: undefined }
  const counts = new Map<string, number>()
  for (const fact of items) counts.set(fact.field_key, (counts.get(fact.field_key) ?? 0) + 1)
  const fields: Record<string, AsOfField> = {}
  for (const [key, field] of Object.entries(found.fields)) {
    fields[key] = {
      value: field.value,
      fromFact: field.source === 'fact',
      possible: field.certainty === 'possible',
      ambiguous: field.ambiguous,
      changes: counts.get(key) ?? 0,
    }
  }
  return { state: found, facts: items, fields }
}

/** Whether the entity's existence periods all start after `t` (not yet), else they ended. */
function notYet(facts: readonly Fact[], t: bigint): boolean {
  const periods = facts.filter((fact) => fact.field_key === EXISTS)
  return periods.every((fact) => fact.valid_from_t !== null && fact.valid_from_t > t)
}

/** The end of the latest existence period that ended by `t`. */
function lastEnd(facts: readonly Fact[], t: bigint): Fact | undefined {
  return facts
    .filter((fact) => fact.field_key === EXISTS && fact.valid_to_t !== null && fact.valid_to_t <= t)
    .toSorted((a, b) => ((a.valid_to_t ?? 0n) < (b.valid_to_t ?? 0n) ? 1 : -1))[0]
}

/**
 * What the time cursor says of the entity (frontend.md §7): it doesn't exist yet or any more
 * ("Died in 1204"), possibly exists (an uncertain date), its existence isn't specified, or it had
 * another name then.
 */
export function ExistenceNote({
  vault,
  entity,
  time,
}: {
  vault: string
  entity: Entity
  time: EntityTime
}) {
  const context = useTimeContext(vault)
  const state = time.state
  if (state === undefined || context.moment === null) return null
  const moment = context.moment
  const when = cursorLabel(context)
  const phrases = PHRASES[entity.kind] ?? DEFAULT_PHRASES
  const date = (fact: Fact | undefined): string | null => {
    if (fact?.valid_to_t == null || context.lens === null || context.dimension === null) {
      return null
    }
    const precision = fact.valid_to?.precision ?? 'base'
    return formatIn(
      context.lens,
      { t: fact.valid_to_t, precision },
      context.dimension,
      context.lenses,
    )
  }
  let text: string | null = null
  let tone = 'border-muted-foreground/30 bg-muted/40'
  if (state.existence === 'not_exists') {
    if (notYet(time.facts, moment)) {
      text = `${phrases.before} (${when}).`
    } else {
      const ended = date(lastEnd(time.facts, moment))
      text = ended === null ? `${phrases.after} (${when}).` : `${phrases.after} ${ended}.`
    }
    tone = 'border-amber-500/40 bg-amber-500/10'
  } else if (state.existence === 'possible') {
    text = `Possibly in existence (${when}): the moment is inside an uncertain date.`
  } else if (state.existence === 'unknown') {
    text = `Existence not specified (${when}).`
  }
  const renamed = state.name !== entity.name
  if (text === null && !renamed) return null
  return (
    <div
      role="status"
      aria-label="As of the time cursor"
      className={`rounded-md border p-3 text-sm ${tone}`}
    >
      {text !== null && <p>{text}</p>}
      {renamed && (
        <p className={state.name_certainty === 'possible' ? 'text-muted-foreground italic' : ''}>
          Known as <strong>{state.name}</strong> then
          {state.name_certainty === 'possible' && ' (possibly: an uncertain date)'}.
        </p>
      )}
    </div>
  )
}
