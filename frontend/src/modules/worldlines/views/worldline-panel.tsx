import type { TimePoint } from '@lore/chronology'
import { Link } from '@tanstack/react-router'
import { ArrowDownIcon, ArrowUpIcon, PencilIcon, ScissorsIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { EntityViewProps } from '@/core/modules'
import { MomentDisplay, TimePointPicker, useDimensionLenses } from '@/core/time'
import {
  fieldErrors,
  useDimensions,
  useEntity,
  useMutations,
  useReplaceSegments,
  useWorldline,
  type SegmentIn,
  type WorldlineSegment,
} from '@/data'

import { absolute, move, rateText, split, toInput } from '../segments'
import { SegmentDialog } from './segment-dialog'
import { TimeTravelDialog } from './time-travel-dialog'

type Editing = { kind: 'edit'; index: number } | { kind: 'add' } | { kind: 'split'; index: number }

/** Errors of one segment of the PUT (`segments.<i>.<field>`), by field. */
function segmentErrors(error: unknown, index: number): Record<string, string> {
  const all = fieldErrors(error)
  const prefix = `segments.${index}.`
  const found: Record<string, string> = {}
  for (const [path, message] of Object.entries(all)) {
    if (path.startsWith(prefix)) found[path.slice(prefix.length)] = message
    else if (!/^segments\.\d+/.test(path)) found[''] = message
  }
  return found
}

/** Split a segment at a moment of its dimension. */
function SplitDialog({
  vault,
  segment,
  pending,
  onSplit,
  onClose,
}: {
  vault: string
  segment: WorldlineSegment
  pending: boolean
  onSplit: (at: TimePoint) => void
  onClose: () => void
}) {
  const { dimension, lenses } = useDimensionLenses(vault, segment.dimension_id)
  const [at, setAt] = useState<TimePoint | null>(null)
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Split segment {segment.seq}</DialogTitle>
        </DialogHeader>
        {dimension === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <TimePointPicker
            vault={vault}
            dimension={dimension}
            lenses={lenses}
            value={at}
            onChange={setAt}
            label="Split at"
          />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={at === null || pending}
            onClick={() => {
              if (at !== null) onSplit(at)
            }}
          >
            Split
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SegmentRow({
  vault,
  segment,
  names,
  editable,
  last,
  pending,
  onEdit,
  onSplit,
  onMove,
  onRemove,
}: {
  vault: string
  segment: WorldlineSegment
  names: ReadonlyMap<string, string>
  editable: boolean
  last: boolean
  pending: boolean
  onEdit: () => void
  onSplit: () => void
  onMove: (delta: number) => void
  onRemove: () => void
}) {
  const rate = rateText(segment.rate)
  const moment = (t: bigint | null) =>
    t === null ? (
      '…'
    ) : (
      <MomentDisplay
        vault={vault}
        dimension={segment.dimension_id}
        moment={{ t, precision: 'base' }}
      />
    )
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
      <span className="font-medium text-muted-foreground">{segment.seq}.</span>
      <span>{names.get(segment.dimension_id) ?? 'Dimension'}</span>
      <span>
        {moment(segment.start_t)} – {moment(segment.end_t)}
      </span>
      {rate !== '' && <Badge variant="outline">{rate}</Badge>}
      {segment.time_status !== null && segment.time_status !== 'ok' && (
        <Badge variant="destructive">{segment.time_status}</Badge>
      )}
      {segment.note !== null && (
        <span className="text-xs text-muted-foreground">{segment.note}</span>
      )}
      <div className="flex-1" />
      {editable && (
        <span className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Edit segment ${segment.seq}`}
            disabled={pending}
            onClick={onEdit}
          >
            <PencilIcon aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Split segment ${segment.seq}`}
            disabled={pending}
            onClick={onSplit}
          >
            <ScissorsIcon aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Move segment ${segment.seq} up`}
            disabled={pending || segment.seq === 1}
            onClick={() => {
              onMove(-1)
            }}
          >
            <ArrowUpIcon aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Move segment ${segment.seq} down`}
            disabled={pending || last}
            onClick={() => {
              onMove(1)
            }}
          >
            <ArrowDownIcon aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove segment ${segment.seq}`}
            disabled={pending}
            onClick={onRemove}
          >
            <Trash2Icon aria-hidden />
          </Button>
        </span>
      )}
    </li>
  )
}

/**
 * The worldline panel (docs/modules/worldlines.md, UI) on kinds that can have one: the segments in
 * the entity's own order (dimension, span, rate), or a note that it lives its lifespan (the
 * implicit worldline). Authors add, edit, split, reorder and remove segments (the list is saved
 * as a whole) and open the **Time travel…** wizard.
 */
export function WorldlinePanel({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const worldline = useWorldline(vault, entityId)
  const dimensions = useDimensions(vault)
  const save = useReplaceSegments(vault, entityId)
  const editable = useMutations() !== null && entity.data?.deleted_at === null
  const [editing, setEditing] = useState<Editing | null>(null)
  const [travelling, setTravelling] = useState(false)
  const names = new Map((dimensions.data?.items ?? []).map((item) => [item.id, item.name]))
  const data = worldline.data
  if (data === undefined) return <p className="text-sm text-muted-foreground">Loading…</p>
  const segments = data.segments
  const inputs = segments.map(toInput)
  const write = (next: SegmentIn[], done?: () => void) => {
    save.mutate(next, {
      onSuccess: () => {
        setEditing(null)
        done?.()
      },
    })
  }
  const home = entity.data?.dimension_id ?? null
  const blank: SegmentIn = {
    dimension_id: segments.at(-1)?.dimension_id ?? home ?? '',
    timeline_id: '',
    start: absolute(0n) as SegmentIn['start'],
    end: absolute(0n) as SegmentIn['end'],
  }
  const lastDimension = segments.at(-1)?.dimension_id ?? home
  const edited = editing?.kind === 'edit' ? inputs[editing.index] : undefined
  const splitting = editing?.kind === 'split' ? segments[editing.index] : undefined

  return (
    <div className="flex flex-col gap-3">
      {data.implicit ? (
        <p className="text-sm text-muted-foreground">
          {segments.length === 0
            ? 'No worldline: this entity has no home dimension.'
            : 'Lives its lifespan in order (no time travel). Add a segment or travel to give it a worldline of its own.'}
        </p>
      ) : null}
      {segments.length > 0 && (
        <ol aria-label="Worldline segments" className="flex flex-col gap-1.5">
          {segments.map((segment, index) => (
            <SegmentRow
              key={segment.id ?? `implicit-${index}`}
              vault={vault}
              segment={segment}
              names={names}
              editable={editable && !data.implicit}
              last={index === segments.length - 1}
              pending={save.isPending}
              onEdit={() => {
                setEditing({ kind: 'edit', index })
              }}
              onSplit={() => {
                setEditing({ kind: 'split', index })
              }}
              onMove={(delta) => {
                write(move(inputs, index, delta))
              }}
              onRemove={() => {
                write(inputs.filter((_, i) => i !== index))
              }}
            />
          ))}
        </ol>
      )}
      <div className="flex flex-wrap gap-2">
        {editable && (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditing({ kind: 'add' })
              }}
            >
              Add segment
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={segments.length === 0}
              onClick={() => {
                setTravelling(true)
              }}
            >
              Time travel…
            </Button>
            {!data.implicit && (
              <Button
                variant="ghost"
                size="sm"
                disabled={save.isPending}
                onClick={() => {
                  if (window.confirm('Remove every segment and live the lifespan again?')) {
                    write([], () => toast.success('Back to the lifespan'))
                  }
                }}
              >
                Clear worldline
              </Button>
            )}
          </>
        )}
        <Button variant="ghost" size="sm" asChild>
          <Link
            to="/v/$vault/m/$module/$"
            params={{ vault, module: 'worldlines', _splat: `entities/${entityId}` }}
          >
            Personal timeline
          </Link>
        </Button>
      </div>
      {editing?.kind === 'add' && (
        <SegmentDialog
          vault={vault}
          title="New segment"
          initial={blank}
          errors={segmentErrors(save.error, data.implicit ? 0 : inputs.length)}
          pending={save.isPending}
          onSave={(segment) => {
            write([...(data.implicit ? [] : inputs), segment])
          }}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
      {editing?.kind === 'edit' && edited !== undefined && (
        <SegmentDialog
          vault={vault}
          title={`Segment ${editing.index + 1}`}
          initial={edited}
          errors={segmentErrors(save.error, editing.index)}
          pending={save.isPending}
          onSave={(segment) => {
            write(inputs.map((each, i) => (i === editing.index ? segment : each)))
          }}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
      {editing?.kind === 'split' && splitting !== undefined && (
        <SplitDialog
          vault={vault}
          segment={splitting}
          pending={save.isPending}
          onSplit={(at) => {
            write(split(inputs, editing.index, at))
          }}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
      {save.isError && editing === null && (
        <p role="alert" className="text-sm text-destructive">
          {Object.values(fieldErrors(save.error))[0] ?? 'The worldline couldn’t be saved.'}
        </p>
      )}
      {travelling && (
        <TimeTravelDialog
          vault={vault}
          entityId={entityId}
          name={entity.data?.name ?? 'The entity'}
          fromDimensionId={lastDimension}
          onClose={() => {
            setTravelling(false)
          }}
        />
      )}
    </div>
  )
}
