import { PencilIcon, PlusIcon, TrashIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { SpanDisplay } from '@/core/time'
import { useDeleteFact, useEntity, useFacts, useMutations, type Fact } from '@/data'

import { FieldDisplay } from './editors'
import { EXISTS, FactForm } from './fact-form'
import type { FieldDef } from './schema'

const moment = (t: bigint | null, precision: string | undefined) =>
  t === null ? null : { t, precision: precision ?? 'base' }

/** Whether two facts' periods overlap (open bounds are unbounded; the end is excluded). */
export function overlaps(a: Fact, b: Fact): boolean {
  if (a.timeline_id !== b.timeline_id) return false
  const startsBeforeEnd = (start: bigint | null, end: bigint | null) =>
    start === null || end === null || start < end
  return (
    startsBeforeEnd(a.valid_from_t, b.valid_to_t) && startsBeforeEnd(b.valid_from_t, a.valid_to_t)
  )
}

function SourceName({ vault, id }: { vault: string; id: string }) {
  const event = useEntity(vault, id)
  return <span>{event.data?.name ?? '…'}</span>
}

/**
 * The history of a temporal field, the existence periods or the names of an entity (its facts,
 * time-model.md §10.2-§10.4): each value with its period, source event and note, edited and
 * deleted in place; new values below. Overlapping values of a single-valued field are flagged
 * (the latest start wins, `core.fact.overlap`).
 */
export function FactHistory({
  vault,
  entity,
  fieldKey,
  field,
  labels,
  empty = 'No values over time yet.',
  addLabel = 'Add a value',
  renderValue,
}: {
  vault: string
  entity: { id: string; kind: string; dimension_id: string | null }
  fieldKey: string
  field?: FieldDef
  labels?: { from: string; to: string }
  empty?: string
  addLabel?: string
  /** How a fact's value shows (default: the field's display). */
  renderValue?: (fact: Fact) => ReactNode
}) {
  const editable = useMutations() !== null
  const facts = useFacts(vault, entity.id, { field: fieldKey })
  const remove = useDeleteFact(vault)
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const items = facts.data?.items ?? []
  const single = fieldKey !== EXISTS && field?.multiple !== true
  const dimension = entity.dimension_id
  const formProps = {
    vault,
    entity,
    fieldKey,
    ...(field === undefined ? {} : { field }),
    ...(labels === undefined ? {} : { labels }),
  }

  return (
    <div className="flex flex-col gap-2">
      {facts.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!facts.isPending && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
      <ul className="flex flex-col gap-1">
        {items.map((fact) => {
          const clashes = single ? items.filter((o) => o.id !== fact.id && overlaps(fact, o)) : []
          if (editing === fact.id) {
            return (
              <li key={fact.id}>
                <FactForm
                  {...formProps}
                  fact={fact}
                  onDone={() => {
                    setEditing(null)
                  }}
                  onCancel={() => {
                    setEditing(null)
                  }}
                />
              </li>
            )
          }
          return (
            <li
              key={fact.id}
              aria-label="Value over time"
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-1 py-1 text-sm hover:bg-accent/50"
            >
              <span className="font-medium">
                {renderValue !== undefined ? (
                  renderValue(fact)
                ) : field !== undefined ? (
                  <FieldDisplay vault={vault} field={field} value={fact.value} />
                ) : (
                  String(fact.value)
                )}
              </span>
              <span className="text-muted-foreground">
                {dimension === null ? (
                  `${fact.valid_from_t?.toString() ?? '…'} – ${fact.valid_to_t?.toString() ?? '…'}`
                ) : (
                  <SpanDisplay
                    vault={vault}
                    dimension={dimension}
                    start={moment(fact.valid_from_t, fact.valid_from?.precision)}
                    end={moment(fact.valid_to_t, fact.valid_to?.precision)}
                  />
                )}
              </span>
              {fact.source_event_id !== null && (
                <span className="text-xs text-muted-foreground">
                  caused by <SourceName vault={vault} id={fact.source_event_id} />
                </span>
              )}
              {fact.note && <span className="text-xs text-muted-foreground">{fact.note}</span>}
              {fact.visibility !== 'public' && (
                <span className="text-xs text-muted-foreground">{fact.visibility}</span>
              )}
              {fact.time_status !== null && fact.time_status !== 'ok' && (
                <span className="text-xs text-destructive">{fact.time_status}</span>
              )}
              {clashes.length > 0 && (
                <span role="note" className="text-xs text-amber-700 dark:text-amber-400">
                  Overlaps another value: the later one wins where they overlap.
                </span>
              )}
              {editable && (
                <span className="ml-auto flex gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label="Edit this value"
                    onClick={() => {
                      setEditing(fact.id)
                      setAdding(false)
                    }}
                  >
                    <PencilIcon className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label="Delete this value"
                    disabled={remove.isPending}
                    onClick={() => {
                      remove.mutate(fact.id)
                    }}
                  >
                    <TrashIcon className="size-3.5" />
                  </Button>
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {editable &&
        (adding ? (
          <FactForm
            {...formProps}
            onDone={() => {
              setAdding(false)
            }}
            onCancel={() => {
              setAdding(false)
            }}
          />
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => {
              setAdding(true)
              setEditing(null)
            }}
          >
            <PlusIcon aria-hidden /> {addLabel}
          </Button>
        ))}
    </div>
  )
}
