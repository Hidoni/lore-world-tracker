import { nextOccurrences, type RecurrenceRule } from '@lore/chronology'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatIn, useDisplayLens, type Moment } from '@/core/time'
import {
  ApiError,
  useDeleteOccurrence,
  useEntity,
  useMaterializeOccurrence,
  useOccurrences,
  useUpdateLatest,
  type Entity,
} from '@/data'

import { EventDialog } from '../event-dialog'
import { ordinal, STATE_LABEL } from './occurrence-header'
import { eventTime } from '../event-time'

/** Occurrences per page of the list. */
const PAGE = 20

/**
 * The rule without what only narrows it (its end and exclusions): the window ends of the list are
 * found with it in the browser, then the server lists what really happens in them.
 */
function widened(rule: RecurrenceRule): RecurrenceRule {
  return { ...rule, limit: { kind: 'never' }, exclusions: [] }
}

type Action = { kind: 'edit' | 'sub_event'; id: string } | null

/**
 * A series' occurrences (recurrence.md §7, frontend.md §8): pages of 20 by time (computed and
 * materialized merged by the server, with their numbers), "Show cancelled", and per occurrence:
 * open (materializes it), modify its time, cancel or restore it, add a sub-event, add a note
 * (its page), and revert a customized one to the computed occurrence.
 */
export function OccurrencesSection({
  vault,
  entity,
  editable,
}: {
  vault: string
  entity: Entity
  editable: boolean
}) {
  const time = eventTime(entity)
  const { dimension, lenses, lens } = useDisplayLens(vault, entity.dimension_id)
  const navigate = useNavigate()
  const materialize = useMaterializeOccurrence(vault)
  const update = useUpdateLatest(vault)
  const remove = useDeleteOccurrence(vault)
  const ext = (entity.ext ?? {}) as { series_start_t?: bigint | null }
  const first = ext.series_start_t ?? time.startT
  const [stack, setStack] = useState<bigint[]>([])
  const [cursor, setCursor] = useState<bigint | null>(null)
  const [cancelled, setCancelled] = useState(false)
  const [action, setAction] = useState<Action>(null)
  const from = cursor ?? first
  const rule = time.recurrence

  // The window holding the next 20 occurrences from `from` (by the widened rule).
  let to: bigint | null = null
  if (rule !== null && from !== null && dimension !== null && time.startT !== null) {
    const calendar =
      rule.kind === 'calendar'
        ? (lenses.find((candidate) => candidate.id === rule.calendar_id)?.calendar ?? null)
        : null
    try {
      const upcoming = nextOccurrences(
        widened(rule),
        {
          seriesStart: time.startT,
          end: time.end ?? { kind: 'instant' },
          dimensionDuration: dimension.duration,
          calendar,
        },
        from - 1n,
        PAGE + 1,
      )
      const last = upcoming.at(-1)
      to = upcoming.length > PAGE && last !== undefined ? last.start : dimension.duration + 1n
    } catch {
      to = dimension.duration + 1n
    }
  }
  const list = useOccurrences(
    vault,
    entity.id,
    from === null || to === null ? null : { from, to },
    { includeCancelled: cancelled, limit: 100 },
  )
  const items = list.data?.items ?? []

  if (rule === null) return null
  if (dimension === null || lens === null) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  const precision = time.start?.precision ?? 'base'
  const shown = (t: bigint) =>
    formatIn(lens, { t, precision } satisfies Moment, dimension, lenses) ?? t.toString()

  /** Runs `run` with the occurrence's event, materializing it first when needed. */
  const withEntity = async (key: string, existing: string | null, run: (id: string) => void) => {
    if (existing !== null) {
      run(existing)
      return
    }
    try {
      const result = await materialize.mutateAsync({ event: entity.id, key })
      run(result.entity.id)
    } catch {
      // The mutation toasts its own error.
    }
  }

  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={stack.length === 0}
          onClick={() => {
            setCursor(stack.at(-1) ?? null)
            setStack(stack.slice(0, -1))
          }}
        >
          Earlier
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={to === null || dimension.duration < to}
          onClick={() => {
            if (from === null || to === null) return
            setStack([...stack, from])
            setCursor(to)
          }}
        >
          Later
        </Button>
        {dimension.present !== null && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              if (from !== null) setStack([...stack, from])
              setCursor(dimension.present)
            }}
          >
            From the present
          </Button>
        )}
        <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={cancelled}
            onChange={(event) => {
              setCancelled(event.target.checked)
            }}
          />
          Show cancelled
        </label>
      </div>
      {list.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">
          {list.data?.truncated === true ? 'Too many occurrences here.' : 'No occurrences here.'}
        </p>
      ) : (
        <ul aria-label="Occurrences" className="flex flex-col">
          {items.map((item) => {
            const label = item.number === null ? `Occurrence ${item.key}` : ordinal(item.number)
            const state = item.state
            return (
              <li
                key={item.key}
                aria-label={label}
                className="flex flex-wrap items-center gap-2 border-t py-1"
              >
                <span className="w-14 text-muted-foreground tabular-nums">{label}</span>
                {item.entity_id !== null ? (
                  <Link
                    to="/v/$vault/e/$entity"
                    params={{ vault, entity: item.entity_id }}
                    className={
                      state === 'cancelled' ? 'line-through' : 'underline-offset-2 hover:underline'
                    }
                  >
                    {shown(item.start_t)}
                  </Link>
                ) : (
                  <span>{shown(item.start_t)}</span>
                )}
                {state !== null && <Badge variant="outline">{STATE_LABEL[state] ?? state}</Badge>}
                {editable && (
                  <span className="ml-auto flex flex-wrap gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        void withEntity(item.key, item.entity_id, (id) => {
                          void navigate({
                            to: '/v/$vault/e/$entity',
                            params: { vault, entity: id },
                          })
                        })
                      }}
                    >
                      Open
                    </Button>
                    <OccurrenceActions
                      label={label}
                      entityId={item.entity_id}
                      state={state}
                      busy={materialize.isPending || update.isPending || remove.isPending}
                      onModify={() => {
                        void withEntity(item.key, item.entity_id, (id) => {
                          setAction({ kind: 'edit', id })
                        })
                      }}
                      onSubEvent={() => {
                        void withEntity(item.key, item.entity_id, (id) => {
                          setAction({ kind: 'sub_event', id })
                        })
                      }}
                      onNote={() => {
                        void withEntity(item.key, item.entity_id, (id) => {
                          void navigate({
                            to: '/v/$vault/e/$entity',
                            params: { vault, entity: id },
                          })
                        })
                      }}
                      onCancel={(value) => {
                        void withEntity(item.key, item.entity_id, (id) => {
                          update.mutate({ id, change: { ext: { cancelled: value } } })
                        })
                      }}
                      onRevert={() => {
                        remove.mutate(
                          { event: entity.id, key: item.key },
                          {
                            onError: (error) => {
                              if (
                                error instanceof ApiError &&
                                error.code === 'occurrence_has_sub_events' &&
                                window.confirm(
                                  `${error.detail} Move its sub-events to the trash with it?`,
                                )
                              ) {
                                remove.mutate({
                                  event: entity.id,
                                  key: item.key,
                                  trashSubEvents: true,
                                })
                              } else if (!(error instanceof ApiError)) {
                                toast.error('The occurrence couldn’t be reverted.')
                              } else if (error.code !== 'occurrence_has_sub_events') {
                                toast.error(error.detail)
                              }
                            },
                          },
                        )
                      }}
                    />
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {action !== null && (
        <OccurrenceAction
          vault={vault}
          action={action}
          onClose={() => {
            setAction(null)
          }}
        />
      )}
    </div>
  )
}

function OccurrenceActions({
  label,
  entityId,
  state,
  busy,
  onModify,
  onSubEvent,
  onNote,
  onCancel,
  onRevert,
}: {
  label: string
  entityId: string | null
  state: string | null
  busy: boolean
  onModify: () => void
  onSubEvent: () => void
  onNote: () => void
  onCancel: (cancelled: boolean) => void
  onRevert: () => void
}) {
  return (
    <>
      <Button variant="ghost" size="sm" disabled={busy} onClick={onModify}>
        Modify time
      </Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={onSubEvent}>
        Add sub-event
      </Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={onNote}>
        Add note
      </Button>
      <Button
        variant="ghost"
        size="sm"
        disabled={busy}
        aria-label={state === 'cancelled' ? `Restore ${label}` : `Cancel ${label}`}
        onClick={() => {
          onCancel(state !== 'cancelled')
        }}
      >
        {state === 'cancelled' ? 'Restore' : 'Cancel'}
      </Button>
      {entityId !== null && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          aria-label={`Revert ${label}`}
          title="Back to the computed occurrence"
          onClick={onRevert}
        >
          Revert
        </Button>
      )}
    </>
  )
}

/** The dialog of an occurrence action, once its event is loaded. */
function OccurrenceAction({
  vault,
  action,
  onClose,
}: {
  vault: string
  action: NonNullable<Action>
  onClose: () => void
}) {
  const loaded = useEntity(vault, action.id)
  if (loaded.data === undefined) return null
  const occurrence = loaded.data
  return action.kind === 'edit' ? (
    <EventDialog mode="edit" vault={vault} entity={occurrence} parent={null} onClose={onClose} />
  ) : (
    <EventDialog
      mode="create"
      vault={vault}
      parent={{ id: occurrence.id, name: occurrence.name, dimension_id: occurrence.dimension_id }}
      onClose={onClose}
    />
  )
}
