import type { TimePoint } from '@lore/chronology'
import { formatRational } from '@lore/chronology'
import { PlusIcon, Trash2Icon } from 'lucide-react'
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
import {
  BigNumberInput,
  pointMoment,
  TimePointPicker,
  timeWriteProblem,
  useDimensionLenses,
  type Lens,
} from '@/core/time'
import {
  ApiError,
  fieldErrors,
  useCreateCorrespondence,
  useDimensions,
  useUpdateCorrespondence,
  type CorrespondenceOut,
  type WireTimePoint,
} from '@/data'

import {
  helperRate,
  levelLength,
  previewOf,
  rateDraft,
  rateOf,
  type PointDraft,
  type RateDraft,
} from '../draft'
import { useMomentFormat, SELECT_CLASS } from './format'
import { MappingChart } from './mapping-chart'

let pointSeq = 0
const nextKey = () => `p${++pointSeq}`

function problemOf(error: unknown): string | null {
  if (error === null) return null
  const time = timeWriteProblem(error)
  if (time !== null) return time
  if (error instanceof ApiError) return error.detail
  return 'The correspondence couldn’t be saved.'
}

/** A rational rate: numerator / denominator. */
function RateInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: RateDraft
  onChange: (value: RateDraft) => void
}) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="text-sm">{label}</legend>
      <div className="flex items-center gap-1.5">
        <BigNumberInput
          aria-label={`${label}: units there`}
          value={value.num}
          min={1n}
          onChange={(num) => {
            onChange({ ...value, num })
          }}
          className="w-32"
        />
        <span className="text-muted-foreground">per</span>
        <BigNumberInput
          aria-label={`${label}: units here`}
          value={value.den}
          min={1n}
          onChange={(den) => {
            onChange({ ...value, den })
          }}
          className="w-32"
        />
      </div>
    </fieldset>
  )
}

/** Levels of a lens' calendar, coarse first (Absolute: its base unit). */
function levelsOf(lens: Lens | undefined): { id: string | null; label: string }[] {
  if (lens?.calendar === null || lens === undefined) return [{ id: null, label: 'base units' }]
  const names = new Map(lens.calendar.definition.levels.map((level) => [level.id, level.plural]))
  return [...lens.calendar.levels].reverse().map((id) => ({ id, label: names.get(id) ?? id }))
}

/**
 * "1 day here = 1 year there": a rate from calendar levels of each side (their lengths where the
 * first sync point is, so a month is that month).
 */
function RateHelper({
  lensA,
  lensB,
  atA,
  atB,
  nameA,
  nameB,
  onRate,
}: {
  lensA: Lens | undefined
  lensB: Lens | undefined
  atA: bigint
  atB: bigint
  nameA: string
  nameB: string
  onRate: (rate: RateDraft) => void
}) {
  const id = useId()
  const levelsA = levelsOf(lensA)
  const levelsB = levelsOf(lensB)
  const [here, setHere] = useState<bigint | null>(1n)
  const [there, setThere] = useState<bigint | null>(1n)
  const [levelA, setLevelA] = useState(levelsA.at(-1)?.id ?? null)
  const [levelB, setLevelB] = useState(levelsB.at(-1)?.id ?? null)
  const lengthA = lensA === undefined ? null : levelLength(lensA, levelA, atA)
  const lengthB = lensB === undefined ? null : levelLength(lensB, levelB, atB)
  const rate =
    here === null || there === null || lengthA === null || lengthB === null
      ? null
      : helperRate(here, lengthA, there, lengthB)
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border p-2 text-sm">
      <BigNumberInput
        aria-label={`Amount in ${nameA}`}
        value={here}
        min={1n}
        onChange={setHere}
        className="w-20"
      />
      <select
        aria-label={`Unit in ${nameA}`}
        className={`${SELECT_CLASS} w-auto`}
        value={levelA ?? ''}
        onChange={(event) => {
          setLevelA(event.target.value === '' ? null : event.target.value)
        }}
      >
        {levelsA.map((level) => (
          <option key={level.id ?? ''} value={level.id ?? ''}>
            {level.label}
          </option>
        ))}
      </select>
      <span id={`${id}-here`}>in {nameA} =</span>
      <BigNumberInput
        aria-label={`Amount in ${nameB}`}
        value={there}
        min={1n}
        onChange={setThere}
        className="w-20"
      />
      <select
        aria-label={`Unit in ${nameB}`}
        className={`${SELECT_CLASS} w-auto`}
        value={levelB ?? ''}
        onChange={(event) => {
          setLevelB(event.target.value === '' ? null : event.target.value)
        }}
      >
        {levelsB.map((level) => (
          <option key={level.id ?? ''} value={level.id ?? ''}>
            {level.label}
          </option>
        ))}
      </select>
      <span>in {nameB}</span>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={rate === null}
        onClick={() => {
          if (rate !== null) onRate({ num: rate.num, den: rate.den })
        }}
      >
        Use for both rates
      </Button>
    </div>
  )
}

/** Maps a moment typed in one dimension through the draft (the TS engine, no request). */
function ConversionTester({
  preview,
  sides,
}: {
  preview: ReturnType<typeof previewOf>
  sides: readonly {
    id: string
    name: string
    lenses: Lens[]
    dimension: NonNullable<ReturnType<typeof useDimensionLenses>['dimension']>
    format: (t: bigint) => string
  }[]
}) {
  const [direction, setDirection] = useState<'ab' | 'ba'>('ab')
  const [value, setValue] = useState<TimePoint | null>(null)
  const from = direction === 'ab' ? sides[0] : sides[1]
  const to = direction === 'ab' ? sides[1] : sides[0]
  if (from === undefined || to === undefined) return null
  const t = value === null ? null : pointMoment(value, from.lenses)
  const result =
    preview.kind !== 'ok' || t === null
      ? undefined
      : preview.correspondence.map(t, direction, to.dimension.duration)
  return (
    <section aria-label="Conversion tester" className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium">Try a moment</h3>
        <div className="flex-1" />
        <select
          aria-label="Direction"
          className={`${SELECT_CLASS} w-auto`}
          value={direction}
          onChange={(event) => {
            setDirection(event.target.value === 'ba' ? 'ba' : 'ab')
            setValue(null)
          }}
        >
          <option value="ab">
            {sides[0]?.name} → {sides[1]?.name}
          </option>
          <option value="ba">
            {sides[1]?.name} → {sides[0]?.name}
          </option>
        </select>
      </div>
      <TimePointPicker
        key={from.id}
        dimension={from.dimension}
        lenses={from.lenses}
        value={value}
        onChange={setValue}
        label={`Moment in ${from.name}`}
      />
      <p className="text-sm" data-testid="conversion-result" aria-live="polite">
        {preview.kind !== 'ok'
          ? 'Complete the sync points to try moments.'
          : t === null
            ? 'Enter a moment.'
            : result === null || result === undefined
              ? `Nothing in ${to.name} happens at the same time.`
              : `${to.format(result)} in ${to.name}`}
      </p>
    </section>
  )
}

/**
 * The correspondence editor (docs/modules/correspondences.md, UI): the other dimension (when
 * new), a name, sync points with a time point picker per side (each in its own dimension's
 * calendars), extrapolation and its rates (with the "1 day here = 1 year there" helper), the
 * mapping chart and a conversion tester. The preview compiles the draft in the browser as soon
 * as every sync point's moments are known; relative anchors resolve when saved.
 */
export function CorrespondenceEditor({
  vault,
  dimensionId,
  existing,
  onClose,
}: {
  vault: string
  /** The dimension whose overview opened it (side A of a new correspondence). */
  dimensionId: string
  existing?: CorrespondenceOut
  onClose: () => void
}) {
  const id = useId()
  const dimensions = useDimensions(vault)
  const create = useCreateCorrespondence(vault)
  const update = useUpdateCorrespondence(vault)
  const save = existing === undefined ? create : update
  const sideA = existing?.dimension_a_id ?? dimensionId
  const others = (dimensions.data?.items ?? []).filter((item) => item.id !== sideA)
  const [chosenB, setChosenB] = useState<string | null>(existing?.dimension_b_id ?? null)
  const sideB = chosenB ?? others[0]?.id ?? null
  const a = useDimensionLenses(vault, sideA)
  const b = useDimensionLenses(vault, sideB)
  const formatA = useMomentFormat(vault, sideA)
  const formatB = useMomentFormat(vault, sideB)
  const dimA = a.dimension
  const dimB = b.dimension
  const nameA = a.dimension?.name ?? 'This dimension'
  const nameB = b.dimension?.name ?? 'the other dimension'
  const [name, setName] = useState(existing?.name ?? '')
  const [points, setPoints] = useState<PointDraft[]>(() =>
    existing === undefined
      ? [{ key: nextKey(), a: null, b: null }]
      : existing.points.map((point) => ({
          key: nextKey(),
          a: point.a as TimePoint | null,
          b: point.b as TimePoint | null,
        })),
  )
  const [extrapolation, setExtrapolation] = useState<'none' | 'rate'>(
    existing?.extrapolation ?? 'none',
  )
  const [before, setBefore] = useState<RateDraft>(rateDraft(existing?.rate_before ?? null))
  const [after, setAfter] = useState<RateDraft>(rateDraft(existing?.rate_after ?? null))
  const errors = fieldErrors(save.error)
  const problem = problemOf(save.error)
  const preview = previewOf(points, a.lenses, b.lenses, extrapolation, before, after)
  const complete = points.every((point) => point.a !== null && point.b !== null)
  const ready = name.trim() !== '' && sideB !== null && complete && !save.isPending

  const setPoint = (key: string, patch: Partial<PointDraft>) => {
    setPoints((current) =>
      current.map((point) => (point.key === key ? { ...point, ...patch } : point)),
    )
  }
  const firstA = points[0]?.a === null || points[0] === undefined ? null : points[0].a
  const firstB = points[0]?.b === null || points[0] === undefined ? null : points[0].b
  const atA = (firstA === null ? null : pointMoment(firstA, a.lenses)) ?? 0n
  const atB = (firstB === null ? null : pointMoment(firstB, b.lenses)) ?? 0n

  const submit = () => {
    if (!ready) return
    const wire = (rate: RateDraft) => {
      const value = rateOf(rate)
      return value === null ? null : formatRational(value)
    }
    const body = {
      name: name.trim(),
      extrapolation,
      rate_before: extrapolation === 'rate' ? wire(before) : null,
      rate_after: extrapolation === 'rate' ? wire(after) : null,
      points: points.map((point) => ({
        a: point.a as WireTimePoint,
        b: point.b as WireTimePoint,
      })),
    }
    const done = () => {
      toast.success(`Correspondence “${body.name}” saved`)
      onClose()
    }
    if (existing === undefined) {
      create.mutate({ ...body, dimension_a_id: sideA, dimension_b_id: sideB }, { onSuccess: done })
    } else {
      update.mutate(
        { id: existing.id, body: { ...body, revision: existing.revision } },
        { onSuccess: done },
      )
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {existing === undefined ? 'New correspondence' : 'Edit correspondence'}
          </DialogTitle>
          <DialogDescription>
            Sync points say which moments of the two dimensions happen at the same time; between
            them time flows evenly. Points must move forward in both dimensions together.
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
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-name`}>Name</Label>
              <Input
                id={`${id}-name`}
                maxLength={300}
                value={name}
                placeholder="The Portal"
                aria-invalid={errors.name !== undefined}
                onChange={(event) => {
                  setName(event.target.value)
                }}
              />
              {errors.name !== undefined && (
                <p className="text-sm text-destructive">{errors.name}</p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-other`}>Corresponds with</Label>
              <select
                id={`${id}-other`}
                className={SELECT_CLASS}
                value={sideB ?? ''}
                disabled={existing !== undefined}
                onChange={(event) => {
                  setChosenB(event.target.value)
                  setPoints((current) => current.map((point) => ({ ...point, b: null })))
                }}
              >
                {others.length === 0 && <option value="">No other dimensions</option>}
                {others.map((other) => (
                  <option key={other.id} value={other.id}>
                    {other.name}
                  </option>
                ))}
              </select>
              {errors.dimension_b_id !== undefined && (
                <p className="text-sm text-destructive">{errors.dimension_b_id}</p>
              )}
            </div>
          </div>

          <section aria-label="Sync points" className="flex flex-col gap-3">
            <h3 className="text-sm font-medium">Sync points</h3>
            {dimA === null || dimB === null ? (
              <p className="text-sm text-muted-foreground">Loading the dimensions…</p>
            ) : (
              points.map((point, index) => (
                <fieldset
                  key={point.key}
                  aria-label={`Sync point ${index + 1}`}
                  className="grid items-start gap-3 rounded-md border p-3 sm:grid-cols-[1fr_1fr_auto]"
                >
                  <div className="flex flex-col gap-1">
                    <TimePointPicker
                      vault={vault}
                      dimension={dimA}
                      lenses={a.lenses}
                      value={point.a}
                      onChange={(value) => {
                        setPoint(point.key, { a: value })
                      }}
                      label={`In ${nameA}`}
                    />
                    {errors[`points.${index}.a`] !== undefined && (
                      <p className="text-sm text-destructive">{errors[`points.${index}.a`]}</p>
                    )}
                  </div>
                  <div className="flex flex-col gap-1">
                    <TimePointPicker
                      key={sideB}
                      vault={vault}
                      dimension={dimB}
                      lenses={b.lenses}
                      value={point.b}
                      onChange={(value) => {
                        setPoint(point.key, { b: value })
                      }}
                      label={`In ${nameB}`}
                    />
                    {errors[`points.${index}.b`] !== undefined && (
                      <p className="text-sm text-destructive">{errors[`points.${index}.b`]}</p>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove sync point ${index + 1}`}
                    disabled={points.length === 1}
                    onClick={() => {
                      setPoints((current) => current.filter((each) => each.key !== point.key))
                    }}
                  >
                    <Trash2Icon aria-hidden />
                  </Button>
                  {errors[`points.${index}`] !== undefined && (
                    <p className="text-sm text-destructive sm:col-span-3">
                      {errors[`points.${index}`]}
                    </p>
                  )}
                </fieldset>
              ))
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => {
                setPoints((current) => [...current, { key: nextKey(), a: null, b: null }])
              }}
            >
              <PlusIcon aria-hidden /> Add sync point
            </Button>
          </section>

          <section aria-label="Extrapolation" className="flex flex-col gap-2">
            <Label htmlFor={`${id}-extrapolation`}>Outside the sync points</Label>
            <select
              id={`${id}-extrapolation`}
              className={SELECT_CLASS}
              value={extrapolation}
              onChange={(event) => {
                setExtrapolation(event.target.value === 'rate' ? 'rate' : 'none')
              }}
            >
              <option value="none">No correspondence (undefined)</option>
              <option value="rate">Continue at a rate</option>
            </select>
            {extrapolation === 'rate' && (
              <>
                <p className="text-xs text-muted-foreground">
                  Base units of {nameB} per base unit of {nameA}. Leave a rate empty to continue the
                  slope of the nearest sync points.
                </p>
                <RateHelper
                  lensA={a.lenses[0]}
                  lensB={b.lenses[0]}
                  atA={atA}
                  atB={atB}
                  nameA={nameA}
                  nameB={nameB}
                  onRate={(rate) => {
                    setBefore(rate)
                    setAfter(rate)
                  }}
                />
                <div className="flex flex-wrap gap-4">
                  <RateInput label="Rate before" value={before} onChange={setBefore} />
                  <RateInput label="Rate after" value={after} onChange={setAfter} />
                </div>
                {(errors.rate_before ?? errors.rate_after) !== undefined && (
                  <p className="text-sm text-destructive">
                    {errors.rate_before ?? errors.rate_after}
                  </p>
                )}
              </>
            )}
          </section>

          {preview.kind === 'invalid' && (
            <p className="text-sm text-destructive" role="status">
              {preview.message}
            </p>
          )}
          {preview.kind === 'ok' && a.dimension !== null && b.dimension !== null && (
            <MappingChart
              correspondence={preview.correspondence}
              durationA={a.dimension.duration}
              durationB={b.dimension.duration}
              nameA={nameA}
              nameB={nameB}
              formatA={formatA}
              formatB={formatB}
            />
          )}
          {a.dimension !== null && b.dimension !== null && sideB !== null && (
            <ConversionTester
              preview={preview}
              sides={[
                {
                  id: sideA,
                  name: nameA,
                  lenses: a.lenses,
                  dimension: a.dimension,
                  format: formatA,
                },
                {
                  id: sideB,
                  name: nameB,
                  lenses: b.lenses,
                  dimension: b.dimension,
                  format: formatB,
                },
              ]}
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
            <Button type="submit" disabled={!ready}>
              {save.isPending ? 'Saving…' : 'Save correspondence'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
