import type { EndSpec, TimePoint } from '@lore/chronology'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { EndSpecPicker, TimePointPicker, timeWriteProblem, useDimensionLenses } from '@/core/time'
import {
  ApiError,
  fieldErrors,
  useCreateEntity,
  useDimensions,
  useQuickSearch,
  useTimelines,
  useUpdateLatest,
  type Entity,
} from '@/data'

import { eventTime, IMPORTANCE } from './event-time'

/** What the timeline select needs of a timeline tree node. */
interface TimelineNode {
  id: string
  name: string
  is_prime: boolean
  trashed: boolean
  children: readonly TimelineNode[]
}

const SELECT_CLASS =
  'h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

interface Parent {
  id: string
  name: string
}

/** What the dialog does: create an event (maybe under a parent), or edit one. */
export type EventDialogMode =
  | {
      mode: 'create'
      /** The dimension to start in (the parent's when there is one). */
      dimensionId?: string | null
      parent?: (Parent & { dimension_id: string | null }) | null
      initialName?: string
    }
  | { mode: 'edit'; entity: Entity; parent: Parent | null }

function flatten(
  nodes: readonly TimelineNode[],
  depth = 0,
): { node: TimelineNode; depth: number }[] {
  return nodes.flatMap((node) => [
    ...(node.trashed ? [] : [{ node, depth }]),
    ...flatten(node.children, depth + 1),
  ])
}

/** A parent event: search the dimension's events, or none. */
function ParentField({
  vault,
  dimensionId,
  self,
  value,
  onChange,
}: {
  vault: string
  dimensionId: string | null
  self: string | null
  value: Parent | null
  onChange: (parent: Parent | null) => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim()
  const results = useQuickSearch(vault, {
    q,
    kind: ['event'],
    ...(dimensionId === null ? {} : { dimension: dimensionId }),
  })
  const hits = q === '' ? [] : (results.data?.items ?? []).filter((hit) => hit.entity_id !== self)
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium">Parent event</legend>
      <div className="flex items-center gap-2 text-sm">
        <span className="flex-1">{value === null ? 'None' : value.name}</span>
        {value !== null && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              onChange(null)
            }}
          >
            Remove parent
          </Button>
        )}
      </div>
      <Input
        aria-label="Search parent events"
        placeholder="Search events…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
        }}
      />
      {hits.length > 0 && (
        <ul aria-label="Parent events" className="flex max-h-36 flex-col overflow-y-auto text-sm">
          {hits.map((hit) => (
            <li key={hit.entity_id}>
              <button
                type="button"
                className="w-full rounded-sm px-2 py-1 text-left hover:bg-accent"
                onClick={() => {
                  onChange({ id: hit.entity_id, name: hit.name })
                  setQuery('')
                }}
              >
                {hit.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  )
}

/** Why a save was refused, in words (`null`: no message beyond the fields). */
function saveProblem(error: unknown): string | null {
  if (error === null) return null
  const time = timeWriteProblem(error)
  if (time !== null) return time
  if (error instanceof ApiError) return error.detail
  return 'The event couldn’t be saved.'
}

type EventFormProps = {
  vault: string
  /** Cancel, or done saving. */
  onClose: () => void
  /** Called with the created or updated event. */
  onSaved?: (entity: Entity) => void
} & EventDialogMode

/**
 * The event form (frontend.md §7, time-model.md §9): name, dimension and timeline (on creation;
 * an event's timeline can't change), start (`TimePointPicker`, relative anchors included), end
 * (`EndSpecPicker`), parent event, importance and category. Server problems with the dates are
 * shown under them. Used by `EventDialog` and by the "New…" dialog for the event kind.
 */
export function EventForm({ vault, onClose, onSaved, ...props }: EventFormProps) {
  const editing = props.mode === 'edit' ? props.entity : null
  const initial = editing === null ? null : eventTime(editing)
  const dimensions = useDimensions(vault)
  const create = useCreateEntity(vault)
  const update = useUpdateLatest(vault, { toast: false })
  const id = useId()
  const [name, setName] = useState(props.mode === 'create' ? (props.initialName ?? '') : '')
  const [dimensionChoice, setDimension] = useState<string | null>(
    props.mode === 'create'
      ? (props.parent?.dimension_id ?? props.dimensionId ?? null)
      : props.entity.dimension_id,
  )
  const dimensionId = dimensionChoice ?? dimensions.data?.items[0]?.id ?? null
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const timelines = useTimelines(vault, editing === null ? dimensionId : null)
  const [timelineChoice, setTimeline] = useState<string | null>(null)
  const timelineOptions = flatten(timelines.data?.items ?? [])
  const timelineId =
    timelineChoice ??
    timelineOptions.find((option) => option.node.is_prime)?.node.id ??
    timelineOptions[0]?.node.id ??
    null
  const [start, setStart] = useState<TimePoint | null>(initial?.start ?? null)
  const [end, setEnd] = useState<EndSpec | null>(initial?.end ?? { kind: 'instant' })
  const [parent, setParent] = useState<Parent | null>(props.parent ?? null)
  const [importance, setImportance] = useState(initial?.importance ?? 3)
  const [category, setCategory] = useState(initial?.category ?? '')
  const pending = create.isPending || update.isPending
  const error = editing === null ? create.error : update.error
  const errors = fieldErrors(error)
  const problem = saveProblem(error)
  const owner = (slot: string) =>
    editing === null ? undefined : { type: 'event', id: editing.id, slot }

  const ready =
    start !== null &&
    end !== null &&
    (editing !== null || (name.trim() !== '' && dimension !== null))

  const submit = () => {
    if (start === null || end === null) return
    const times = { start, end, importance, category: category.trim() || null }
    if (editing === null) {
      create.mutate(
        {
          kind: 'event',
          name: name.trim(),
          dimension_id: dimensionId,
          parent_id: parent?.id ?? null,
          ext: { ...times, ...(timelineId === null ? {} : { timeline_id: timelineId }) },
        },
        {
          onSuccess: (result) => {
            onSaved?.(result.entity)
            onClose()
          },
        },
      )
    } else {
      update.mutate(
        {
          id: editing.id,
          change: {
            ...(parent?.id === props.parent?.id ? {} : { parent_id: parent?.id ?? null }),
            ext: times,
          },
        },
        {
          onSuccess: (result) => {
            onSaved?.(result.entity)
            onClose()
          },
        },
      )
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      {editing === null && (
        <>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-name`}>Name</Label>
            <Input
              id={`${id}-name`}
              maxLength={300}
              value={name}
              aria-invalid={errors.name !== undefined}
              onChange={(event) => {
                setName(event.target.value)
              }}
            />
            {errors.name !== undefined && <p className="text-sm text-destructive">{errors.name}</p>}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-dimension`}>Dimension</Label>
              <select
                id={`${id}-dimension`}
                className={SELECT_CLASS}
                value={dimensionId ?? ''}
                disabled={parent !== null}
                onChange={(event) => {
                  setDimension(event.target.value)
                  setTimeline(null)
                }}
              >
                {(dimensions.data?.items ?? []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-timeline`}>Timeline</Label>
              <select
                id={`${id}-timeline`}
                className={SELECT_CLASS}
                value={timelineId ?? ''}
                onChange={(event) => {
                  setTimeline(event.target.value)
                }}
              >
                {timelineOptions.map(({ node, depth }) => (
                  <option key={node.id} value={node.id}>
                    {'  '.repeat(depth)}
                    {node.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </>
      )}
      {dimension === null ? (
        <p className="text-sm text-muted-foreground">
          {dimensions.data?.items.length === 0
            ? 'Create a dimension first: events happen in one.'
            : 'Loading the dimension…'}
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-1">
            <TimePointPicker
              key={dimension.id}
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              value={start}
              onChange={setStart}
              owner={owner('start')}
              label="Start"
            />
            {errors['ext.start'] !== undefined && (
              <p className="text-sm text-destructive">{errors['ext.start']}</p>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <EndSpecPicker
              key={dimension.id}
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              start={start}
              value={end}
              onChange={setEnd}
              owner={owner('end')}
            />
            {errors['ext.end'] !== undefined && (
              <p className="text-sm text-destructive">{errors['ext.end']}</p>
            )}
          </div>
        </>
      )}
      <ParentField
        vault={vault}
        dimensionId={dimensionId}
        self={editing?.id ?? null}
        value={parent}
        onChange={setParent}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-importance`}>Importance</Label>
          <select
            id={`${id}-importance`}
            className={SELECT_CLASS}
            value={importance}
            onChange={(event) => {
              setImportance(Number(event.target.value))
            }}
          >
            {[1, 2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                {level} · {IMPORTANCE[level]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-category`}>Category</Label>
          <Input
            id={`${id}-category`}
            maxLength={200}
            placeholder="Battle, treaty, festival…"
            value={category}
            onChange={(event) => {
              setCategory(event.target.value)
            }}
          />
        </div>
      </div>
      {problem !== null && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={!ready || pending}>
          {pending ? 'Saving…' : editing === null ? 'Create event' : 'Save'}
        </Button>
      </DialogFooter>
    </form>
  )
}

/** `EventForm` in a dialog: create an event (maybe under a parent), or edit one. */
export function EventDialog(props: EventFormProps) {
  const editing = props.mode === 'edit' ? props.entity : null
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) props.onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing === null ? 'New event' : `Edit ${editing.name}`}</DialogTitle>
          <DialogDescription>
            When it happens, how long it lasts, and where it sits among other events.
          </DialogDescription>
        </DialogHeader>
        <EventForm {...props} />
      </DialogContent>
    </Dialog>
  )
}
