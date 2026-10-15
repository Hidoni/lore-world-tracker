import type { TimePoint } from '@lore/chronology'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { BigNumberInput, flattenTimelines, TimePointPicker, useDimensionLenses } from '@/core/time'
import { useDimensions, useTimelines, type SegmentIn, type WireTimePoint } from '@/data'

export const SELECT_CLASS =
  'h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

/** A dimension and one of its timelines (the prime first). */
export function PlaceFields({
  vault,
  dimensionId,
  timelineId,
  onChange,
  prefix,
}: {
  vault: string
  dimensionId: string | null
  timelineId: string | null
  onChange: (dimensionId: string, timelineId: string | null) => void
  prefix: string
}) {
  const dimensions = useDimensions(vault)
  const timelines = useTimelines(vault, dimensionId)
  const options = flattenTimelines(timelines.data?.items ?? []).filter(({ node }) => !node.trashed)
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${prefix}-dimension`}>Dimension</Label>
        <select
          id={`${prefix}-dimension`}
          className={SELECT_CLASS}
          value={dimensionId ?? ''}
          onChange={(event) => {
            onChange(event.target.value, null)
          }}
        >
          {(dimensions.data?.items ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${prefix}-timeline`}>Timeline</Label>
        <select
          id={`${prefix}-timeline`}
          className={SELECT_CLASS}
          value={timelineId ?? options[0]?.node.id ?? ''}
          onChange={(event) => {
            if (dimensionId !== null) onChange(dimensionId, event.target.value)
          }}
        >
          {options.map(({ node, depth }) => (
            <option key={node.id} value={node.id}>
              {'  '.repeat(depth)}
              {node.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

/** Its timeline, defaulting to the dimension's prime once the tree has loaded. */
export function useTimelineOrPrime(
  vault: string,
  dimensionId: string | null,
  chosen: string | null,
) {
  const timelines = useTimelines(vault, dimensionId)
  const prime = timelines.data?.items[0]?.id ?? null
  return chosen ?? prime
}

/** A rate as numerator / denominator (subjective units per unit of the dimension). */
export function RateFields({
  value,
  onChange,
}: {
  value: { num: bigint | null; den: bigint | null }
  onChange: (value: { num: bigint | null; den: bigint | null }) => void
}) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-sm">Rate (lived time per time of the world)</legend>
      <div className="flex items-center gap-1.5">
        <BigNumberInput
          aria-label="Rate: lived"
          value={value.num}
          min={1n}
          onChange={(num) => {
            onChange({ ...value, num })
          }}
          className="w-28"
        />
        <span className="text-muted-foreground">per</span>
        <BigNumberInput
          aria-label="Rate: world"
          value={value.den}
          min={1n}
          onChange={(den) => {
            onChange({ ...value, den })
          }}
          className="w-28"
        />
      </div>
    </fieldset>
  )
}

/**
 * Add or edit one segment of a worldline: where (dimension, timeline), from when to when (time
 * points of that dimension, anchorable to its events), the rate time passes for the entity and a
 * note. The whole worldline is saved by the caller.
 */
export function SegmentDialog({
  vault,
  title,
  initial,
  errors,
  pending,
  onSave,
  onClose,
}: {
  vault: string
  title: string
  initial: SegmentIn
  errors: Record<string, string>
  pending: boolean
  onSave: (segment: SegmentIn) => void
  onClose: () => void
}) {
  const id = useId()
  const [dimensionId, setDimension] = useState<string | null>(initial.dimension_id || null)
  const [chosenTimeline, setTimeline] = useState<string | null>(initial.timeline_id || null)
  const timelineId = useTimelineOrPrime(vault, dimensionId, chosenTimeline)
  const [start, setStart] = useState<TimePoint | null>(initial.start as TimePoint | null)
  const [end, setEnd] = useState<TimePoint | null>(initial.end as TimePoint | null)
  const [rate, setRate] = useState({
    num: BigInt(initial.rate?.num ?? '1'),
    den: BigInt(initial.rate?.den ?? '1'),
  } as { num: bigint | null; den: bigint | null })
  const [note, setNote] = useState(initial.note ?? '')
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const ready =
    dimensionId !== null &&
    timelineId !== null &&
    start !== null &&
    end !== null &&
    rate.num !== null &&
    rate.den !== null &&
    !pending

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Where the entity is, from when to when, and how fast time passes for it there.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            if (!ready || rate.num === null || rate.den === null) return
            onSave({
              ...initial,
              dimension_id: dimensionId,
              timeline_id: timelineId,
              start: start as WireTimePoint,
              end: end as WireTimePoint,
              rate: { num: rate.num.toString(), den: rate.den.toString() },
              note: note.trim() === '' ? null : note.trim(),
            })
          }}
        >
          <PlaceFields
            vault={vault}
            prefix={id}
            dimensionId={dimensionId}
            timelineId={timelineId}
            onChange={(nextDimension, nextTimeline) => {
              if (nextDimension !== dimensionId) {
                setStart(null)
                setEnd(null)
              }
              setDimension(nextDimension)
              setTimeline(nextTimeline)
            }}
          />
          {dimension === null ? (
            <p className="text-sm text-muted-foreground">Loading the dimension…</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <TimePointPicker
                  key={`${dimension.id}-start`}
                  vault={vault}
                  dimension={dimension}
                  lenses={lenses}
                  value={start}
                  onChange={setStart}
                  label="From"
                />
                {errors.start !== undefined && (
                  <p className="text-sm text-destructive">{errors.start}</p>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <TimePointPicker
                  key={`${dimension.id}-end`}
                  vault={vault}
                  dimension={dimension}
                  lenses={lenses}
                  value={end}
                  onChange={setEnd}
                  label="Until"
                />
                {errors.end !== undefined && (
                  <p className="text-sm text-destructive">{errors.end}</p>
                )}
              </div>
            </div>
          )}
          <RateFields value={rate} onChange={setRate} />
          {errors.rate !== undefined && <p className="text-sm text-destructive">{errors.rate}</p>}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-note`}>Note</Label>
            <Textarea
              id={`${id}-note`}
              rows={2}
              value={note}
              onChange={(event) => {
                setNote(event.target.value)
              }}
            />
          </div>
          {errors[''] !== undefined && (
            <p role="alert" className="text-sm text-destructive">
              {errors['']}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ready}>
              {pending ? 'Saving…' : 'Save segment'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
