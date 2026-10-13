import type { TimePoint } from '@lore/chronology'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { EXISTS, FactHistory } from '@/core/fields'
import type { Kind } from '@/core/registry'
import { TimePointPicker, useDimensionLenses, useDisplayLens, useTimeContext } from '@/core/time'
import {
  useCreateEntity,
  useCreateFact,
  useFacts,
  useMutations,
  useUpdateFact,
  type Entity,
  type Fact,
  type WireTimePoint,
} from '@/data'

/** How a kind names the start and end of its existence, and the events that mark them. */
const WORDS: Record<string, { from: string; to: string; start: string; end: string }> = {
  character: { from: 'Born', to: 'Died', start: 'Birth', end: 'Death' },
  group: { from: 'Founded', to: 'Dissolved', start: 'Founding', end: 'Dissolution' },
  location: { from: 'Founded', to: 'Destroyed', start: 'Founding', end: 'Destruction' },
  species: { from: 'Emerged', to: 'Extinct', start: 'Emergence', end: 'Extinction' },
  language: { from: 'Emerged', to: 'Extinct', start: 'Emergence', end: 'Extinction' },
}
const DEFAULT_WORDS = { from: 'From', to: 'Until', start: 'Beginning', end: 'End' }

export function existenceWords(kind: string) {
  return WORDS[kind] ?? DEFAULT_WORDS
}

/** A time point anchored to the start of an event (time-model.md §5.2). */
function atEventStart(eventId: string): WireTimePoint {
  return {
    anchor: {
      kind: 'relative',
      ref: { type: 'event', id: eventId, slot: 'start' },
      offset: { kind: 'base', units: '0' },
    },
    precision: 'base',
  }
}

/**
 * "Create a birth event and anchor the start of existence to it" (time-model.md §10.4): a new
 * event at the picked moment, and the existence period's bound anchored to its start (the only
 * period with that bound open, else a new period).
 */
function EventShortcut({
  vault,
  entity,
  edge,
  facts,
  onDone,
}: {
  vault: string
  entity: Entity
  edge: 'start' | 'end'
  facts: readonly Fact[]
  onDone: () => void
}) {
  const words = existenceWords(entity.kind)
  const context = useTimeContext(vault)
  const dimensionId = entity.dimension_id ?? context.dimensionId
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const { lens } = useDisplayLens(vault, dimensionId)
  const [point, setPoint] = useState<TimePoint | null>(null)
  const createEntity = useCreateEntity(vault)
  const createFact = useCreateFact(vault)
  const updateFact = useUpdateFact(vault)
  const busy = createEntity.isPending || createFact.isPending || updateFact.isPending
  const error = createEntity.error ?? createFact.error ?? updateFact.error
  const noun = edge === 'start' ? words.start : words.end
  const timeline =
    (dimensionId === context.dimensionId ? context.timelineId : dimension?.primeTimelineId) ?? null
  if (dimension === null || dimensionId === null) return null

  const create = (): void => {
    if (point === null || timeline === null) return
    createEntity.mutate(
      {
        kind: 'event',
        name: `${noun} of ${entity.name}`,
        dimension_id: dimensionId,
        ext: { start: point, end: { kind: 'instant' }, importance: 3, category: null },
      },
      {
        onSuccess: (result) => {
          const bound = atEventStart(result.entity.id)
          const key = edge === 'start' ? 'valid_from' : 'valid_to'
          const open = facts.filter((fact) =>
            edge === 'start' ? fact.valid_from === null : fact.valid_to === null,
          )
          const only = open.length === 1 ? open[0] : undefined
          if (only !== undefined) {
            updateFact.mutate(
              {
                id: only.id,
                body: { revision: only.revision, [key]: bound, source_event_id: result.entity.id },
              },
              { onSuccess: onDone },
            )
          } else {
            createFact.mutate(
              {
                entity: entity.id,
                body: {
                  field_key: EXISTS,
                  timeline_id: timeline,
                  [key]: bound,
                  source_event_id: result.entity.id,
                },
              },
              { onSuccess: onDone },
            )
          }
        },
      },
    )
  }

  return (
    <div
      className="flex flex-col gap-2 rounded-md border p-3"
      role="group"
      aria-label={`New ${noun.toLowerCase()} event`}
    >
      <p className="text-sm">
        A new event, <strong>{`${noun} of ${entity.name}`}</strong>, and the{' '}
        {edge === 'start' ? 'start' : 'end'} of the lifespan anchored to it.
      </p>
      <TimePointPicker
        dimension={dimension}
        lenses={lenses}
        value={point}
        onChange={setPoint}
        displayLens={lens}
        label="When"
      />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error.message}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={point === null || timeline === null || busy}
          onClick={create}
        >
          Create {noun.toLowerCase()} event
        </Button>
      </div>
    </div>
  )
}

/**
 * The lifespan of an entity whose kind has existence (frontend.md §7, time-model.md §10.4): its
 * existence periods with the kind's words (Born/Died, Founded/Dissolved…), edited in place,
 * several periods allowed, and shortcuts creating the birth or death event and anchoring the
 * period to it.
 */
export function Lifespan({
  vault,
  entity,
  kind,
}: {
  vault: string
  entity: Entity
  kind: Kind | undefined
}) {
  const editable = useMutations() !== null && entity.deleted_at === null
  const facts = useFacts(vault, entity.id, { field: EXISTS })
  const [shortcut, setShortcut] = useState<'start' | 'end' | null>(null)
  if (kind?.capabilities.has_existence !== true) return null
  const words = existenceWords(entity.kind)
  const items = facts.data?.items ?? []
  return (
    <section aria-label="Lifespan" className="flex flex-col gap-2 rounded-md border p-4">
      <h2 className="font-medium">Lifespan</h2>
      <FactHistory
        vault={vault}
        entity={entity}
        fieldKey={EXISTS}
        labels={{ from: words.from, to: words.to }}
        empty="Existence not specified: it counts as existing at every time."
        addLabel="Add a period"
        renderValue={() => `${words.from} – ${words.to}`}
      />
      {editable && shortcut === null && (
        <div className="flex flex-wrap gap-2">
          {(['start', 'end'] as const).map((edge) => (
            <Button
              key={edge}
              variant="outline"
              size="sm"
              onClick={() => {
                setShortcut(edge)
              }}
            >
              Create {(edge === 'start' ? words.start : words.end).toLowerCase()} event…
            </Button>
          ))}
        </div>
      )}
      {editable && shortcut !== null && (
        <EventShortcut
          vault={vault}
          entity={entity}
          edge={shortcut}
          facts={items}
          onDone={() => {
            setShortcut(null)
          }}
        />
      )}
    </section>
  )
}
