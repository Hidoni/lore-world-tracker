import { GitBranchIcon, PencilIcon, PlusIcon, TrashIcon, Undo2Icon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  recordPlace,
  RecordBranchBadge,
  SpanDisplay,
  useBranching,
  useTimeContext,
} from '@/core/time'
import {
  useDeleteFact,
  useEntity,
  useFacts,
  useMutations,
  useRevertOverride,
  type Fact,
} from '@/data'

import { FieldDisplay } from './editors'
import { EXISTS, FactForm, OverrideFactForm } from './fact-form'
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
 * (the latest start wins, `core.fact.overlap`). In a branch it lists the values the branch sees:
 * inherited ones are badged, the shared past is read-only and values still valid at the branch
 * point are edited in this timeline (an override, which Revert removes).
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
  const time = useTimeContext(vault)
  const branching = useBranching(vault)
  // In a branch of the entity's dimension: the values that branch sees (overrides included).
  const branch =
    branching.inBranch &&
    branching.timelineId !== null &&
    (entity.dimension_id === null || entity.dimension_id === time.dimensionId)
      ? branching.timelineId
      : null
  const facts = useFacts(
    vault,
    entity.id,
    branch === null ? { field: fieldKey } : { field: fieldKey, timeline: branch },
  )
  const remove = useDeleteFact(vault)
  const revert = useRevertOverride(vault)
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
          const place =
            branch === null
              ? null
              : recordPlace(branching.lineage, {
                  timelineId: fact.timeline_id,
                  start: fact.valid_from_t,
                  end: fact.valid_to_t,
                  overridesId: fact.overrides_id ?? null,
                })
          if (editing === fact.id && branch !== null && place !== null && place.kind !== 'own') {
            return (
              <li key={fact.id}>
                <OverrideFactForm
                  {...formProps}
                  fact={fact}
                  rootId={fact.overrides_id ?? fact.id}
                  timelineId={branch}
                  branchName={branching.name(branch)}
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
                    startPoint={fact.valid_from}
                    endPoint={fact.valid_to}
                  />
                )}
              </span>
              <RecordBranchBadge place={place} branchName={branching.name(branch)} />
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
              {editable && (place === null || place.kind === 'own') && (
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
              {editable && place !== null && place.kind !== 'own' && place.kind !== 'past' && (
                <span className="ml-auto flex gap-0.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7"
                    onClick={() => {
                      setEditing(fact.id)
                      setAdding(false)
                    }}
                  >
                    <GitBranchIcon className="size-3.5" aria-hidden /> Edit in this timeline
                  </Button>
                  {place.kind === 'override' && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label="Revert to the inherited value"
                      disabled={revert.isPending}
                      onClick={() => {
                        revert.mutate({ recordType: 'fact', id: fact.id })
                      }}
                    >
                      <Undo2Icon className="size-3.5" />
                    </Button>
                  )}
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
