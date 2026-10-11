import { floorDiv, formatAbsolute, formatInteger } from '@lore/chronology'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type ReactNode } from 'react'

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
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  useCalendarPresets,
  useCalendarPreview,
  useCreateDimension,
  type components,
} from '@/data'

import { BigNumberInput } from './big-number-input'
import { SELECT_CLASS } from './select'

type Preset = components['schemas']['PresetOut']

/** Seconds in a Julian year (365.25 days): the calculator presets' "year". */
const YEAR_SECONDS = 31_557_600n

/** Lifetimes to start from, in seconds (converted to base units). */
const DURATION_PRESETS: { label: string; seconds: bigint }[] = [
  { label: '10,000 years', seconds: 10_000n * YEAR_SECONDS },
  { label: '13.8 billion years', seconds: 13_800_000_000n * YEAR_SECONDS },
  { label: '10^100 years of 365.25 days', seconds: 10n ** 100n * YEAR_SECONDS },
]

const STEPS = ['Name', 'Base unit', 'Duration', 'First calendar', 'Review'] as const

interface Draft {
  name: string
  summary: string
  singular: string
  plural: string
  abbr: string
  /** How long one base unit lasts: `num / den` seconds. */
  num: bigint | null
  den: bigint | null
  duration: bigint | null
  presetId: string | null
  calendarName: string
  /** The moment the preset's alignment unit starts ("Year 1 begins at"). */
  origin: bigint | null
}

const INITIAL: Draft = {
  name: '',
  summary: '',
  singular: 'second',
  plural: 'seconds',
  abbr: 's',
  num: 1n,
  den: 1n,
  duration: null,
  presetId: null,
  calendarName: '',
  origin: 0n,
}

/** Seconds as base units of `num / den` seconds each (rounded down). */
function toUnits(seconds: bigint, num: bigint, den: bigint): bigint {
  return floorDiv(seconds * den, num)
}

/**
 * The base units a preset's absolute anchors reach (chronology-engine.md §13): the dimension must
 * last at least this long, or the calendar won't compile.
 */
function presetNeeds(preset: Preset, draft: Draft): bigint | null {
  if (draft.num === null || draft.den === null || draft.origin === null) return null
  return draft.origin + toUnits(BigInt(preset.duration_seconds), draft.num, draft.den)
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  )
}

/** Problems of the create request, in words, with the step they belong to. */
function createProblems(error: unknown): { step: number; message: string }[] {
  if (!(error instanceof ApiError))
    return [{ step: 4, message: 'The dimension couldn’t be created.' }]
  const items =
    error.errors.length > 0 ? error.errors : [{ path: '', message: error.detail, code: error.code }]
  return items.map((item) => {
    const path = item.path.replace(/^body\./, '')
    const step =
      path.startsWith('name') || path.startsWith('summary')
        ? 0
        : path.startsWith('ext.base_unit') || path.includes('seconds_per_base_unit')
          ? 1
          : path.startsWith('ext.duration')
            ? 2
            : path.startsWith('calendar') || path.startsWith('/')
              ? 3
              : 4
    return { step, message: item.message }
  })
}

/**
 * The dimension wizard (R-DIM-1, R-DIM-5): name and description, the base unit (its names and how
 * many seconds it lasts), the duration `D` (with lifetimes to start from), the first calendar from
 * a preset (live server preview, "Year 1 begins at"), then a review. Creating it makes the
 * dimension, its prime timeline and its default calendar in one change, then opens it.
 */
export function DimensionWizard({ vault, onClose }: { vault: string; onClose: () => void }) {
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState(INITIAL)
  const id = useId()
  const navigate = useNavigate()
  const presets = useCalendarPresets(vault)
  const create = useCreateDimension(vault)
  const set = (patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...patch }))
  }
  const preset = presets.data?.items.find((item) => item.id === draft.presetId) ?? null
  const needs = preset === null ? null : presetNeeds(preset, draft)
  const tooShort = needs !== null && draft.duration !== null && draft.duration < needs
  const unit = {
    singular: draft.singular.trim(),
    plural: draft.plural.trim(),
    abbr: draft.abbr.trim(),
  }
  const source =
    preset === null || draft.num === null || draft.den === null || draft.origin === null
      ? null
      : {
          preset: {
            id: preset.id,
            seconds_per_base_unit: { num: draft.num.toString(), den: draft.den.toString() },
            origin: draft.origin.toString(),
          },
        }
  const preview = useCalendarPreview(
    vault,
    step >= 3 && source !== null && draft.duration !== null && !tooShort
      ? { time_spec: { base_unit: unit, duration: draft.duration.toString() }, source }
      : null,
  )
  const previewError =
    preview.error instanceof ApiError
      ? (preview.error.errors[0]?.message ?? preview.error.detail)
      : null

  const valid = [
    draft.name.trim() !== '',
    unit.singular !== '' &&
      unit.plural !== '' &&
      unit.abbr !== '' &&
      draft.num !== null &&
      draft.num > 0n &&
      draft.den !== null &&
      draft.den > 0n,
    draft.duration !== null && draft.duration >= 1n,
    source !== null && !tooShort && preview.data?.ok === true && !preview.isPlaceholderData,
    true,
  ]
  const problems = create.isError ? createProblems(create.error) : []

  const submit = () => {
    if (source === null || draft.duration === null) return
    create.mutate(
      {
        name: draft.name.trim(),
        summary: draft.summary.trim(),
        ext: { base_unit: unit, duration: draft.duration.toString() },
        calendar: {
          name: draft.calendarName.trim() || (preset?.name ?? 'Calendar'),
          source,
        },
      },
      {
        onSuccess: (created) => {
          onClose()
          void navigate({
            to: '/v/$vault/d/$dimension',
            params: { vault, dimension: created.dimension.id },
          })
        },
      },
    )
  }

  const durationText =
    draft.duration === null
      ? '—'
      : formatAbsolute(draft.duration, { ...unit, abbr: unit.abbr || '?' })

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>New dimension</DialogTitle>
          <DialogDescription>
            Step {step + 1} of {STEPS.length}: {STEPS[step]}
          </DialogDescription>
        </DialogHeader>
        <ol aria-label="Steps" className="flex flex-wrap gap-1 text-xs">
          {STEPS.map((title, index) => (
            <li
              key={title}
              aria-current={index === step ? 'step' : undefined}
              className={
                index === step
                  ? 'rounded-full bg-primary px-2 py-0.5 text-primary-foreground'
                  : 'rounded-full bg-muted px-2 py-0.5 text-muted-foreground'
              }
            >
              {title}
            </li>
          ))}
        </ol>
        <form
          id={`${id}-form`}
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (!valid[step]) return
            if (step < STEPS.length - 1) setStep(step + 1)
            else submit()
          }}
        >
          {step === 0 && (
            <>
              <Field label="Name" htmlFor={`${id}-name`}>
                <Input
                  id={`${id}-name`}
                  maxLength={300}
                  value={draft.name}
                  onChange={(event) => {
                    set({ name: event.target.value })
                  }}
                />
              </Field>
              <Field label="Description" htmlFor={`${id}-summary`}>
                <Textarea
                  id={`${id}-summary`}
                  value={draft.summary}
                  onChange={(event) => {
                    set({ summary: event.target.value })
                  }}
                />
              </Field>
            </>
          )}
          {step === 1 && (
            <>
              <p className="text-sm text-muted-foreground">
                Time is counted in whole base units from the dimension’s inception. Pick the
                smallest step you will ever need.
              </p>
              <div className="grid grid-cols-3 gap-2">
                <Field label="Singular" htmlFor={`${id}-singular`}>
                  <Input
                    id={`${id}-singular`}
                    value={draft.singular}
                    onChange={(event) => {
                      set({ singular: event.target.value })
                    }}
                  />
                </Field>
                <Field label="Plural" htmlFor={`${id}-plural`}>
                  <Input
                    id={`${id}-plural`}
                    value={draft.plural}
                    onChange={(event) => {
                      set({ plural: event.target.value })
                    }}
                  />
                </Field>
                <Field label="Abbreviation" htmlFor={`${id}-abbr`}>
                  <Input
                    id={`${id}-abbr`}
                    value={draft.abbr}
                    onChange={(event) => {
                      set({ abbr: event.target.value })
                    }}
                  />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Seconds per unit" htmlFor={`${id}-num`}>
                  <BigNumberInput
                    id={`${id}-num`}
                    value={draft.num}
                    min={1n}
                    onChange={(num) => {
                      set({ num })
                    }}
                  />
                </Field>
                <Field label="Divided by" htmlFor={`${id}-den`}>
                  <BigNumberInput
                    id={`${id}-den`}
                    value={draft.den}
                    min={1n}
                    onChange={(den) => {
                      set({ den })
                    }}
                  />
                </Field>
              </div>
              <p className="text-xs text-muted-foreground">
                Presets use this to line up real-world calendars (1 / 1000 for milliseconds).
              </p>
            </>
          )}
          {step === 2 && (
            <>
              <Field label={`Duration (${unit.plural || 'units'})`} htmlFor={`${id}-duration`}>
                <BigNumberInput
                  id={`${id}-duration`}
                  value={draft.duration}
                  min={1n}
                  onChange={(duration) => {
                    set({ duration })
                  }}
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                {DURATION_PRESETS.map((choice) => (
                  <Button
                    key={choice.label}
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={draft.num === null || draft.den === null}
                    onClick={() => {
                      if (draft.num !== null && draft.den !== null) {
                        set({ duration: toUnits(choice.seconds, draft.num, draft.den) })
                      }
                    }}
                  >
                    {choice.label}
                  </Button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                From the inception (0) to the end of time (D). It can grow later; it can only shrink
                while every moment stays inside.
              </p>
            </>
          )}
          {step === 3 && (
            <>
              <Field label="Preset" htmlFor={`${id}-preset`}>
                <select
                  id={`${id}-preset`}
                  className={SELECT_CLASS}
                  value={draft.presetId ?? ''}
                  onChange={(event) => {
                    const chosen = presets.data?.items.find(
                      (item) => item.id === event.target.value,
                    )
                    set({ presetId: chosen?.id ?? null, calendarName: chosen?.name ?? '' })
                  }}
                >
                  <option value="">Choose a calendar…</option>
                  {(presets.data?.items ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </Field>
              {preset !== null && (
                <>
                  <p className="text-sm text-muted-foreground">{preset.description}</p>
                  <Field label="Calendar name" htmlFor={`${id}-calendar-name`}>
                    <Input
                      id={`${id}-calendar-name`}
                      value={draft.calendarName}
                      onChange={(event) => {
                        set({ calendarName: event.target.value })
                      }}
                    />
                  </Field>
                  <Field
                    label={`Year 1 begins at (${unit.plural || 'units'} since the inception)`}
                    htmlFor={`${id}-origin`}
                  >
                    <BigNumberInput
                      id={`${id}-origin`}
                      value={draft.origin}
                      min={0n}
                      {...(draft.duration === null ? {} : { max: draft.duration })}
                      onChange={(origin) => {
                        set({ origin })
                      }}
                    />
                  </Field>
                  <p className="text-xs text-muted-foreground">Its origin: {preset.origin}.</p>
                  {tooShort && (
                    <p role="alert" className="text-sm text-destructive">
                      This calendar needs the dimension to last at least {formatInteger(needs)}{' '}
                      {unit.plural}: lengthen the duration or move year 1 earlier.
                    </p>
                  )}
                  {previewError !== null && (
                    <p role="alert" className="text-sm text-destructive">
                      {previewError}
                    </p>
                  )}
                  {preview.data !== undefined && !preview.data.ok && (
                    <ul role="alert" className="text-sm text-destructive">
                      {preview.data.errors.map((problem) => (
                        <li key={`${problem.path}:${problem.code}`}>{problem.message}</li>
                      ))}
                    </ul>
                  )}
                  {preview.data?.ok === true && (
                    <section aria-label="Preview" className="rounded-md border p-2 text-sm">
                      <p className="mb-1 text-xs text-muted-foreground">The first years begin:</p>
                      <ul>
                        {preview.data.samples.map((sample) => (
                          <li key={sample.t} className="flex justify-between gap-2">
                            <span>{sample.display}</span>
                            <span className="font-mono text-xs text-muted-foreground">
                              t = {formatInteger(BigInt(sample.t))}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                </>
              )}
            </>
          )}
          {step === 4 && (
            <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Name</dt>
              <dd>{draft.name}</dd>
              <dt className="text-muted-foreground">Base unit</dt>
              <dd>
                {unit.singular} / {unit.plural} ({unit.abbr}),{' '}
                {draft.den === 1n ? `${draft.num} s` : `${draft.num} / ${draft.den} s`}
              </dd>
              <dt className="text-muted-foreground">Duration</dt>
              <dd>{durationText}</dd>
              <dt className="text-muted-foreground">First calendar</dt>
              <dd>
                {draft.calendarName || preset?.name} ({preset?.name}), year 1 at t ={' '}
                {draft.origin === null ? '—' : formatInteger(draft.origin)}
              </dd>
            </dl>
          )}
          {problems.length > 0 && (
            <ul role="alert" className="text-sm text-destructive">
              {problems.map((problem, index) => (
                <li key={index}>
                  {problem.message}
                  {problem.step !== step && problem.step < STEPS.length && (
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      onClick={() => {
                        setStep(problem.step)
                      }}
                    >
                      Go to {STEPS[problem.step]}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </form>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              if (step === 0) onClose()
              else setStep(step - 1)
            }}
          >
            {step === 0 ? 'Cancel' : 'Back'}
          </Button>
          <Button type="submit" form={`${id}-form`} disabled={!valid[step] || create.isPending}>
            {step < STEPS.length - 1 ? 'Next' : create.isPending ? 'Creating…' : 'Create dimension'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
