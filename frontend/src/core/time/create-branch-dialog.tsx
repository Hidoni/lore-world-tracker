import type { TimePoint } from '@lore/chronology'
import { useId, useState } from 'react'
import { toast } from 'sonner'

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
import { Textarea } from '@/components/ui/textarea'
import { ApiError, fieldErrors, useCreateBranch, type Entity, type WireTimePoint } from '@/data'

import { useBranching } from './branching'
import { useDimensionLenses, useTimeContext } from './time-context'
import { TimePointPicker } from './time-point-picker'
import { timeWriteProblem } from './time-problems'

const SELECT_CLASS =
  'h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

export interface CreateBranchOptions {
  /** The timeline to branch (default: the viewed one). */
  parentTimelineId?: string | null
  /** Where to branch (the timeline's "Branch here": the moment clicked; an event's start/end). */
  initialPoint?: TimePoint | null
  /** A name to begin with ("What if …"). */
  initialName?: string
}

/** Why the branch couldn't be created, in words (`null`: no message beyond the fields). */
function createProblem(error: unknown): string | null {
  if (error === null) return null
  const time = timeWriteProblem(error)
  if (time !== null) return time
  if (error instanceof ApiError) return error.detail
  return 'The branch couldn’t be created.'
}

/**
 * The create-branch dialog (docs/modules/branches.md, UI): a name, the premise ("What if…"), the
 * timeline to branch and the branch point, which may be anchored to an event of that timeline (it
 * then moves with it). On success the new branch becomes the viewed timeline.
 */
export function CreateBranchDialog({
  vault,
  onClose,
  onCreated,
  parentTimelineId,
  initialPoint = null,
  initialName = '',
}: {
  vault: string
  onClose: () => void
  onCreated?: (timeline: Entity) => void
} & CreateBranchOptions) {
  const id = useId()
  const time = useTimeContext(vault)
  const branching = useBranching(vault)
  const { dimension, lenses, isPending } = useDimensionLenses(vault, time.dimensionId)
  const create = useCreateBranch(vault)
  const [name, setName] = useState(initialName)
  const [premise, setPremise] = useState('')
  const [parent, setParent] = useState<string | null>(
    parentTimelineId ?? branching.timelineId ?? null,
  )
  const [point, setPoint] = useState<TimePoint | null>(initialPoint)
  const errors = fieldErrors(create.error)
  const problem = createProblem(create.error)
  const options = branching.timelines.filter(({ node }) => !node.trashed)
  const chosen = parent ?? options[0]?.node.id ?? null
  const ready = name.trim() !== '' && point !== null && chosen !== null && !create.isPending

  const submit = () => {
    if (!ready) return
    create.mutate(
      {
        parent_timeline_id: chosen,
        branch_point: point as WireTimePoint,
        name: name.trim(),
        summary: premise.trim(),
      },
      {
        onSuccess: (result) => {
          toast.success(`Branch “${result.entity.name}” created`)
          time.setTimeline(result.entity.id)
          onCreated?.(result.entity)
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
          <DialogTitle>New branch</DialogTitle>
          <DialogDescription>
            A “what if” timeline: it shares everything before the branch point with the timeline it
            branches from, and goes its own way after it.
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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-name`}>Name</Label>
            <Input
              id={`${id}-name`}
              maxLength={300}
              value={name}
              placeholder="What if…"
              aria-invalid={errors.name !== undefined}
              onChange={(event) => {
                setName(event.target.value)
              }}
            />
            {errors.name !== undefined && <p className="text-sm text-destructive">{errors.name}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-premise`}>Premise</Label>
            <Textarea
              id={`${id}-premise`}
              rows={2}
              value={premise}
              placeholder="What happens differently in this timeline"
              onChange={(event) => {
                setPremise(event.target.value)
              }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-parent`}>Branch from</Label>
            <select
              id={`${id}-parent`}
              className={SELECT_CLASS}
              value={chosen ?? ''}
              onChange={(event) => {
                setParent(event.target.value)
              }}
            >
              {options.map(({ node, depth }) => (
                <option key={node.id} value={node.id}>
                  {'  '.repeat(depth)}
                  {node.name}
                </option>
              ))}
            </select>
            {errors.parent_timeline_id !== undefined && (
              <p className="text-sm text-destructive">{errors.parent_timeline_id}</p>
            )}
          </div>
          {dimension === null || isPending ? (
            <p className="text-sm text-muted-foreground">Loading the dimension…</p>
          ) : (
            <div className="flex flex-col gap-1">
              <TimePointPicker
                key={dimension.id}
                vault={vault}
                dimension={dimension}
                lenses={lenses}
                value={point}
                onChange={setPoint}
                label="Branch point"
              />
              {errors.branch_point !== undefined && (
                <p className="text-sm text-destructive">{errors.branch_point}</p>
              )}
            </div>
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
            <Button type="submit" disabled={!ready}>
              {create.isPending ? 'Creating…' : 'Create branch'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
