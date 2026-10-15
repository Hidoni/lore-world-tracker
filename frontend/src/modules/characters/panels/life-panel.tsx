import type { Duration } from '@lore/chronology'
import { Link } from '@tanstack/react-router'

import { useActiveModules, type EntityViewProps } from '@/core/modules'
import { elapsedIn, formatDuration, formatIn, useTimeContext, type TimeContext } from '@/core/time'
import {
  useCharacterLife,
  useEntity,
  useFacts,
  useLinks,
  usePersonalTimeline,
  type Fact,
} from '@/data'

const EXISTS = 'core.exists'
const IS_A = 'species.is_a'

/** The character's life in a timeline: the first start and last end of its existence. */
export function lifeBounds(facts: readonly Fact[]): { born: bigint | null; died: bigint | null } {
  const periods = facts.filter((fact) => fact.field_key === EXISTS)
  const starts = periods.map((fact) => fact.valid_from_t)
  const ends = periods.map((fact) => fact.valid_to_t)
  const min = (values: bigint[]) => values.reduce((a, b) => (b < a ? b : a))
  const max = (values: bigint[]) => values.reduce((a, b) => (b > a ? b : a))
  const known = (values: (bigint | null)[]) => values.filter((v): v is bigint => v !== null)
  return {
    // An open start (or end) is unknown: no age then.
    born: periods.length > 0 && !starts.includes(null) ? min(known(starts)) : null,
    died: periods.length > 0 && !ends.includes(null) ? max(known(ends)) : null,
  }
}

function useMeasure(context: TimeContext) {
  const { lens, lenses, dimension } = context
  // Ages read best in a calendar: Absolute falls back to the dimension's first one.
  const measure = lens?.calendar == null ? (lenses.find((c) => c.calendar !== null) ?? lens) : lens
  return {
    age: (from: bigint, to: bigint): string | null =>
      measure === null || dimension === null
        ? null
        : (elapsedIn(measure, from, to, dimension)?.text ?? null),
    date: (t: bigint): string =>
      lens === null || dimension === null
        ? t.toString()
        : (formatIn(lens, { t, precision: 'base' }, dimension, lenses) ?? t.toString()),
  }
}

/**
 * Subjective ages by event (time-model.md §11.3): with the worldlines module on and an explicit
 * worldline (a time traveler), the age at an event is the time the character has lived, from
 * its personal timeline; `null` otherwise (ages are measured from birth).
 */
function useLivedAges(vault: string, entityId: string): ReadonlyMap<string, string> | null {
  const on = useActiveModules(vault).modules.some((module) => module.id === 'worldlines')
  const personal = usePersonalTimeline(vault, entityId, { enabled: on })
  if (!on || personal.data === undefined || personal.data.implicit) return null
  const ages = new Map<string, string>()
  for (const item of personal.data.items) {
    if (item.kind === 'participation' && item.event_id != null && item.age?.display != null) {
      ages.set(item.event_id, item.age.display)
    }
  }
  return ages
}

/** The species' typical lifespan, next to the character's. */
function SpeciesLifespan({ vault, entityId }: { vault: string; entityId: string }) {
  const context = useTimeContext(vault)
  const links = useLinks(vault, entityId, { type: [IS_A], direction: 'out' })
  const speciesId = links.data?.items[0]?.other.id ?? null
  const species = useEntity(vault, speciesId ?? '', {}, { enabled: speciesId !== null })
  const fields = (species.data?.fields ?? {}) as Record<string, unknown>
  const typical = fields.typical_lifespan as Duration | null | undefined
  if (typical == null || context.dimension === null || species.data === undefined) return null
  const text = formatDuration(typical, context.dimension, context.lenses)
  if (text === '') return null
  return (
    <p className="text-sm text-muted-foreground">
      Typical lifespan of {species.data.name}: {text}
    </p>
  )
}

/**
 * The character's life on the time context's timeline (frontend.md §7, time-model.md §10.4):
 * when they were born and died (with their age then), their existence periods, and the events
 * they take part in by start, with their roles and their age at each, next to their species'
 * typical lifespan.
 */
export function LifePanel({ vault, entityId }: EntityViewProps) {
  const context = useTimeContext(vault)
  const { timelineId } = context
  const life = useCharacterLife(vault, entityId, timelineId)
  const facts = useFacts(
    vault,
    entityId,
    timelineId === null ? {} : { field: EXISTS, timeline: timelineId },
    { enabled: timelineId !== null },
  )
  const { age, date } = useMeasure(context)
  const lived = useLivedAges(vault, entityId)
  const items = life.data?.items ?? []
  const periods = (facts.data?.items ?? []).filter((fact) => fact.field_key === EXISTS)
  const { born, died } = lifeBounds(periods)
  if (timelineId === null) {
    return <p className="text-sm text-muted-foreground">Choose a dimension to see its events.</p>
  }
  const lifespan = born !== null && died !== null ? age(born, died) : null
  return (
    <div className="flex flex-col gap-3">
      {(born !== null || died !== null) && (
        <p className="text-sm" aria-label="Lifespan">
          {born !== null && <>Born {date(born)}</>}
          {born !== null && died !== null && ' · '}
          {died !== null && <>Died {date(died)}</>}
          {lifespan !== null && <> (aged {lifespan})</>}
        </p>
      )}
      {periods.length > 1 && (
        <ul aria-label="Existence periods" className="text-xs text-muted-foreground">
          {periods.map((fact) => (
            <li key={fact.id}>
              {fact.valid_from_t === null ? '…' : date(fact.valid_from_t)} –{' '}
              {fact.valid_to_t === null ? '…' : date(fact.valid_to_t)}
            </li>
          ))}
        </ul>
      )}
      <SpeciesLifespan vault={vault} entityId={entityId} />
      {life.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!life.isPending && items.length === 0 && (
        <p className="text-sm text-muted-foreground">Takes part in no events on this timeline.</p>
      )}
      {items.length > 0 && (
        <ol aria-label="Life events" className="flex flex-col gap-1">
          {items.map((item) => {
            // A time traveler's age is the time they have lived, not the time since birth.
            const at =
              lived !== null
                ? (lived.get(item.id) ?? null)
                : born !== null && item.start_t !== null && item.start_t >= born
                  ? age(born, item.start_t)
                  : null
            return (
              <li key={item.id} className="flex gap-3 text-sm">
                <span className="w-40 shrink-0 truncate text-muted-foreground">
                  {item.display.start ?? '—'}
                </span>
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: item.id }}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {item.name}
                </Link>
                {item.roles.length > 0 && (
                  <span className="text-xs text-muted-foreground">as {item.roles.join(', ')}</span>
                )}
                {at !== null && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    {lived !== null ? `lived ${at}` : `age ${at}`}
                  </span>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
