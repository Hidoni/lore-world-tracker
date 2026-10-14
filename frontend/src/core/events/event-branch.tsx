import type { EndSpec, RecurrenceRule, TimePoint } from '@lore/chronology'
import { formatAbsolute } from '@lore/chronology'
import { GitBranchPlusIcon, LockIcon, PencilIcon, Undo2Icon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  CreateBranchDialog,
  EndSpecPicker,
  formatIn,
  recordPlace,
  TimePointPicker,
  timeWriteProblem,
  useBranching,
  useDisplayLens,
  type CreateBranchOptions,
  type RecordPlace,
} from '@/core/time'
import {
  ApiError,
  useBranchDiff,
  useRevertOverride,
  useSaveOverride,
  type DiffRecord,
  type Entity,
  type WireTimePoint,
} from '@/data'

import { eventTime, type EventTime } from './event-time'

const absolute = (t: bigint): TimePoint => ({
  anchor: { kind: 'absolute', t: t.toString() },
  precision: 'base',
})

const relativeTo = (eventId: string, slot: 'start' | 'end'): TimePoint => ({
  anchor: {
    kind: 'relative',
    ref: { type: 'event', id: eventId, slot },
    offset: { kind: 'base', units: '0' },
  },
  precision: 'base',
})

const asMoment = (value: unknown): bigint | null =>
  typeof value === 'string' && /^-?\d+$/.test(value) ? BigInt(value) : null

/** Where an event stands in the viewed timeline, and the branch's override of it if any. */
export interface EventPlace {
  place: RecordPlace | null
  override: DiffRecord | null
  /** The viewed branch (`null`: a prime timeline). */
  branchId: string | null
  branchName: string | null
}

/**
 * Where the event stands in the viewed timeline (docs/modules/branches.md, UI): the branch's own,
 * the shared past (over by the branch point: read-only), still going at the branch point (it can
 * be edited in this timeline: an override), or already overridden here.
 */
export function useEventPlace(vault: string, entity: Entity): EventPlace {
  const branching = useBranching(vault)
  const time = eventTime(entity)
  const branchId = branching.inBranch ? branching.timelineId : null
  const diff = useBranchDiff(vault, branchId)
  if (branchId === null) return { place: null, override: null, branchId, branchName: null }
  const override =
    diff.data?.overridden.find(
      (record) => record.record_type === 'event' && record.entity_id === entity.id,
    ) ?? null
  const place: RecordPlace | null =
    override !== null
      ? { kind: 'override' }
      : recordPlace(branching.lineage, {
          timelineId: time.timelineId,
          start: time.startT,
          end: time.recurring ? time.seriesEndT : time.endT,
        })
  return { place, override, branchId, branchName: branching.name(branchId) }
}

/** "What if…": branch the viewed timeline at the start or the end of this event. */
export function WhatIfMenu({ vault, entity }: { vault: string; entity: Entity }) {
  const branching = useBranching(vault)
  const time = eventTime(entity)
  const [options, setOptions] = useState<CreateBranchOptions | null>(null)
  if (!branching.enabled || time.occurrenceKey !== null) return null
  const branch = (slot: 'start' | 'end') => {
    setOptions({
      parentTimelineId: branching.timelineId,
      initialPoint: relativeTo(entity.id, slot),
      initialName: `What if ${entity.name}…`,
    })
  }
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <GitBranchPlusIcon aria-hidden /> What if…
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            disabled={time.startT === null}
            onSelect={() => {
              branch('start')
            }}
          >
            Branch at its start…
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={time.endT === null}
            onSelect={() => {
              branch('end')
            }}
          >
            Branch at its end…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {options !== null && (
        <CreateBranchDialog
          vault={vault}
          {...options}
          onClose={() => {
            setOptions(null)
          }}
        />
      )}
    </>
  )
}

/** Why an override was refused, in words. */
function overrideProblem(error: unknown): string | null {
  if (error === null) return null
  const time = timeWriteProblem(error)
  if (time !== null) return time
  if (error instanceof ApiError) return error.errors[0]?.message ?? error.detail
  return 'The change couldn’t be saved.'
}

/** The series' last moment as a time point (`until` limit), when the rule ends by date. */
function untilOf(rule: RecurrenceRule | null): TimePoint | null {
  const limit = rule?.limit as { kind?: string; until?: TimePoint } | undefined
  return limit?.kind === 'until' && limit.until !== undefined ? limit.until : null
}

/**
 * Edit in this timeline (time-model.md §4.4): what an event may change after the branch point,
 * its end (or a series' last date). Saving creates or updates the branch's override.
 */
export function OverrideEventDialog({
  vault,
  entity,
  time,
  branchId,
  branchName,
  override,
  onClose,
}: {
  vault: string
  entity: Entity
  time: EventTime
  branchId: string
  branchName: string | null
  override: DiffRecord | null
  onClose: () => void
}) {
  const { dimension, lenses } = useDisplayLens(vault, entity.dimension_id)
  const save = useSaveOverride(vault)
  const overriddenEnd = asMoment(override?.after?.end_t)
  const [end, setEnd] = useState<EndSpec | null>(
    overriddenEnd === null ? time.end : { kind: 'time_point', time_point: absolute(overriddenEnd) },
  )
  const [until, setUntil] = useState<TimePoint | null>(untilOf(time.recurrence))
  const problem = overrideProblem(save.error)
  const series = time.recurring && time.recurrence !== null
  const submit = () => {
    const changes: Record<string, unknown> = {}
    if (series) {
      if (until === null || time.recurrence === null) return
      changes.recurrence = {
        ...time.recurrence,
        limit: { kind: 'until', until: until as WireTimePoint },
      }
    } else {
      if (end === null) return
      changes.end = end
    }
    save.mutate(
      { recordType: 'event', rootId: entity.id, timelineId: branchId, changes },
      {
        onSuccess: () => {
          toast.success(`${entity.name} changed in ${branchName ?? 'this timeline'}`)
          onClose()
        },
      },
    )
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit {entity.name} in this timeline</DialogTitle>
          <DialogDescription>
            Only {branchName ?? 'this branch'} changes. Its start belongs to the shared past, so
            only what happens after the branch point can differ:{' '}
            {series ? 'when the series stops.' : 'when it ends.'}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          {dimension === null ? (
            <p className="text-sm text-muted-foreground">Loading the dimension…</p>
          ) : series ? (
            <TimePointPicker
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              value={until}
              onChange={setUntil}
              label="Last occurrence by"
            />
          ) : (
            <EndSpecPicker
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              start={time.start}
              value={end}
              onChange={setEnd}
              label="End"
            />
          )}
          {problem !== null && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={save.isPending || (series ? until === null : end === null)}
            >
              {save.isPending ? 'Saving…' : 'Save in this timeline'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * The event's standing in the viewed branch: inherited from which timeline, read-only shared
 * past, or changed here (what differs, Edit in this timeline, Revert).
 */
export function EventBranchStatus({
  vault,
  entity,
  editable,
  found,
}: {
  vault: string
  entity: Entity
  editable: boolean
  found: EventPlace
}) {
  const time = eventTime(entity)
  const { dimension, lenses, lens } = useDisplayLens(vault, entity.dimension_id)
  const revert = useRevertOverride(vault)
  const [editing, setEditing] = useState(false)
  const { place, override, branchId, branchName } = found
  if (place === null || place.kind === 'own' || branchId === null) return null
  const shown = (t: bigint | null) =>
    t === null || dimension === null || lens === null
      ? '—'
      : (formatIn(lens, { t, precision: 'base' }, dimension, lenses) ??
        formatAbsolute(t, dimension.baseUnit))
  const before = asMoment(override?.before?.end_t)
  const after = asMoment(override?.after?.end_t)
  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-dashed p-3"
      data-testid="event-branch-status"
    >
      <div className="flex flex-wrap items-center gap-2">
        {'from' in place ? (
          <Badge variant="outline">Inherited from {place.from.name}</Badge>
        ) : (
          <Badge>Changed in {branchName ?? 'this timeline'}</Badge>
        )}
        {place.kind === 'past' && (
          <Badge variant="secondary">
            <LockIcon aria-hidden /> Shared past
          </Badge>
        )}
        <div className="flex-1" />
        {editable && place.kind !== 'past' && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(true)
            }}
          >
            <PencilIcon aria-hidden /> Edit in this timeline
          </Button>
        )}
        {editable && place.kind === 'override' && override !== null && (
          <Button
            variant="ghost"
            size="sm"
            disabled={revert.isPending}
            onClick={() => {
              revert.mutate(
                { recordType: 'event', id: override.id },
                {
                  onSuccess: () => {
                    toast.success(`${entity.name} reverted to the inherited version`)
                  },
                  onError: (error) => {
                    toast.error(overrideProblem(error) ?? 'Couldn’t revert')
                  },
                },
              )
            }}
          >
            <Undo2Icon aria-hidden /> Revert
          </Button>
        )}
      </div>
      {place.kind === 'past' && (
        <p className="text-sm text-muted-foreground">
          This event ended before {branchName ?? 'this branch'} branched off at{' '}
          {shown(place.cutoff)}: it is part of the history the timelines share, so it can’t change
          here. Switch to {place.from.name} to edit it there.
        </p>
      )}
      {place.kind === 'spanning' && (
        <p className="text-sm text-muted-foreground">
          This event was still going when {branchName ?? 'this branch'} branched off at{' '}
          {shown(place.cutoff)}. Its start is shared; how it ends can differ here.
        </p>
      )}
      {place.kind === 'override' && override !== null && (
        <p className="text-sm">
          {after !== null || before !== null
            ? `In this timeline it ends ${shown(after)} instead of ${shown(before)}.`
            : 'In this timeline its series stops differently.'}
        </p>
      )}
      {editing && (
        <OverrideEventDialog
          vault={vault}
          entity={entity}
          time={time}
          branchId={branchId}
          branchName={branchName}
          override={override}
          onClose={() => {
            setEditing(false)
          }}
        />
      )}
    </div>
  )
}
