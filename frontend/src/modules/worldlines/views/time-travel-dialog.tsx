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
import { useActiveModules } from '@/core/modules'
import { TimePointPicker, timeWriteProblem, useDimensionLenses } from '@/core/time'
import {
  ApiError,
  fieldErrors,
  useQuickSearch,
  useTimeTravel,
  type TimeTravelIn,
  type WireTimePoint,
} from '@/data'

import { PlaceFields, RateFields, SELECT_CLASS, useTimelineOrPrime } from './segment-dialog'

type Destination = 'timeline' | 'branch'

/** Search for an event of a dimension (the departure). */
function EventSearch({
  vault,
  dimensionId,
  value,
  onChange,
}: {
  vault: string
  dimensionId: string | null
  value: { id: string; name: string } | null
  onChange: (value: { id: string; name: string } | null) => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim()
  const results = useQuickSearch(vault, {
    q,
    kind: ['event'],
    ...(dimensionId === null ? {} : { dimension: dimensionId }),
  })
  if (value !== null) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium">{value.name}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onChange(null)
          }}
        >
          Change
        </Button>
      </div>
    )
  }
  const hits = q === '' ? [] : (results.data?.items ?? [])
  return (
    <div className="flex flex-col gap-1">
      <Input
        aria-label="Departure event"
        placeholder="Search events…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
        }}
      />
      {hits.length > 0 && (
        <ul className="flex flex-col rounded-md border text-sm" aria-label="Events found">
          {hits.slice(0, 8).map((hit) => (
            <li key={hit.entity_id}>
              <button
                type="button"
                className="w-full px-2 py-1 text-left hover:bg-accent"
                onClick={() => {
                  onChange({ id: hit.entity_id, name: hit.name })
                }}
              >
                {hit.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function problemOf(error: unknown): string | null {
  if (error === null) return null
  const time = timeWriteProblem(error)
  if (time !== null) return time
  if (error instanceof ApiError) return error.detail
  return 'The time travel couldn’t be saved.'
}

/**
 * The **Time travel…** wizard (docs/modules/worldlines.md, UI): when the entity leaves (an event,
 * or a moment, optionally recording a departure event), where it arrives (a timeline of any
 * dimension, or a new "what if" branch), when, until when, at what rate, and an arrival event.
 * One request does all of it (`POST …/time-travel`).
 */
export function TimeTravelDialog({
  vault,
  entityId,
  name,
  fromDimensionId,
  onClose,
}: {
  vault: string
  entityId: string
  name: string
  /** Where the departure is looked for first (the last segment's dimension). */
  fromDimensionId: string | null
  onClose: () => void
}) {
  const id = useId()
  const travel = useTimeTravel(vault, entityId)
  const branchesOn = useActiveModules(vault).modules.some((module) => module.id === 'branches')
  const [departureKind, setDepartureKind] = useState<'event' | 'moment'>('moment')
  const [event, setEvent] = useState<{ id: string; name: string } | null>(null)
  const [at, setAt] = useState<TimePoint | null>(null)
  const [departureName, setDepartureName] = useState('')
  const from = useDimensionLenses(vault, fromDimensionId)
  const [dimensionId, setDimension] = useState<string | null>(fromDimensionId)
  const [chosenTimeline, setTimeline] = useState<string | null>(null)
  const timelineId = useTimelineOrPrime(vault, dimensionId, chosenTimeline)
  const [destination, setDestination] = useState<Destination>('timeline')
  const [branchName, setBranchName] = useState('')
  const [arrival, setArrival] = useState<TimePoint | null>(null)
  const [until, setUntil] = useState<TimePoint | null>(null)
  const [arrivalName, setArrivalName] = useState('')
  const [rate, setRate] = useState<{ num: bigint | null; den: bigint | null }>({
    num: 1n,
    den: 1n,
  })
  const to = useDimensionLenses(vault, dimensionId)
  const errors = fieldErrors(travel.error)
  const problem = problemOf(travel.error)
  const departureReady = departureKind === 'event' ? event !== null : at !== null
  const ready =
    departureReady &&
    dimensionId !== null &&
    arrival !== null &&
    (destination === 'timeline' ? timelineId !== null : branchName.trim() !== '') &&
    rate.num !== null &&
    rate.den !== null &&
    !travel.isPending

  const submit = () => {
    if (!ready) return
    const body: TimeTravelIn = {
      departure:
        departureKind === 'event'
          ? { event_id: event?.id ?? null }
          : {
              at: at as WireTimePoint,
              event_name: departureName.trim() === '' ? null : departureName.trim(),
            },
      destination: {
        dimension_id: dimensionId,
        ...(destination === 'timeline'
          ? { timeline_id: timelineId }
          : { new_branch: { name: branchName.trim() } }),
        arrival: arrival as WireTimePoint,
        until: until === null ? null : (until as WireTimePoint),
        rate:
          rate.num === rate.den || rate.num === null || rate.den === null
            ? null
            : { num: rate.num.toString(), den: rate.den.toString() },
        event_name: arrivalName.trim() === '' ? null : arrivalName.trim(),
      },
      suppress: [],
    }
    travel.mutate(body, {
      onSuccess: () => {
        toast.success(`${name} travelled through time`)
        onClose()
      },
    })
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
          <DialogTitle>Time travel</DialogTitle>
          <DialogDescription>
            {name} leaves at a moment and arrives somewhere else in time: the rest of that stretch
            of their worldline isn’t lived any more, and the new visit comes right after it.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-5"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 font-medium">Departure</legend>
            <div className="flex gap-4 text-sm" role="radiogroup" aria-label="Leave at">
              {(['moment', 'event'] as const).map((kind) => (
                <label key={kind} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name={`${id}-departure`}
                    checked={departureKind === kind}
                    onChange={() => {
                      setDepartureKind(kind)
                    }}
                  />
                  {kind === 'moment' ? 'At a moment' : 'At an event'}
                </label>
              ))}
            </div>
            {departureKind === 'event' ? (
              <EventSearch
                vault={vault}
                dimensionId={fromDimensionId}
                value={event}
                onChange={setEvent}
              />
            ) : from.dimension === null ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <>
                <TimePointPicker
                  vault={vault}
                  dimension={from.dimension}
                  lenses={from.lenses}
                  value={at}
                  onChange={setAt}
                  label="Leaves at"
                />
                <Input
                  aria-label="Departure event name"
                  placeholder="Record a departure event (optional): its name"
                  value={departureName}
                  onChange={(e) => {
                    setDepartureName(e.target.value)
                  }}
                />
              </>
            )}
            {errors.departure !== undefined && (
              <p className="text-sm text-destructive">{errors.departure}</p>
            )}
          </fieldset>

          <fieldset className="flex flex-col gap-3">
            <legend className="mb-1 font-medium">Destination</legend>
            <PlaceFields
              vault={vault}
              prefix={id}
              dimensionId={dimensionId}
              timelineId={timelineId}
              onChange={(nextDimension, nextTimeline) => {
                if (nextDimension !== dimensionId) {
                  setArrival(null)
                  setUntil(null)
                }
                setDimension(nextDimension)
                setTimeline(nextTimeline)
              }}
            />
            {branchesOn && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`${id}-where`}>Arrive in</Label>
                <select
                  id={`${id}-where`}
                  className={SELECT_CLASS}
                  value={destination}
                  onChange={(e) => {
                    setDestination(e.target.value === 'branch' ? 'branch' : 'timeline')
                  }}
                >
                  <option value="timeline">The timeline above</option>
                  <option value="branch">A new branch (“what if”)</option>
                </select>
                {destination === 'branch' && (
                  <Input
                    aria-label="Branch name"
                    placeholder="What if…"
                    value={branchName}
                    onChange={(e) => {
                      setBranchName(e.target.value)
                    }}
                  />
                )}
              </div>
            )}
            {to.dimension === null ? (
              <p className="text-sm text-muted-foreground">Loading the dimension…</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <TimePointPicker
                    key={`${to.dimension.id}-arrival`}
                    vault={vault}
                    dimension={to.dimension}
                    lenses={to.lenses}
                    value={arrival}
                    onChange={setArrival}
                    label="Arrives at"
                  />
                  {errors['destination.arrival'] !== undefined && (
                    <p className="text-sm text-destructive">{errors['destination.arrival']}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  <TimePointPicker
                    key={`${to.dimension.id}-until`}
                    vault={vault}
                    dimension={to.dimension}
                    lenses={to.lenses}
                    value={until}
                    onChange={setUntil}
                    label="Stays until (optional)"
                  />
                  {errors['destination.until'] !== undefined && (
                    <p className="text-sm text-destructive">{errors['destination.until']}</p>
                  )}
                </div>
              </div>
            )}
            <RateFields value={rate} onChange={setRate} />
            <Input
              aria-label="Arrival event name"
              placeholder="Record an arrival event (optional): its name"
              value={arrivalName}
              onChange={(e) => {
                setArrivalName(e.target.value)
              }}
            />
          </fieldset>
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
              {travel.isPending ? 'Travelling…' : 'Travel'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
