import {
  type CompiledCalendar,
  type TimePoint,
  type ValidationError,
  DateError,
  formatMoment,
  unitBounds,
  validateCalendar,
} from '@lore/chronology'
import { absoluteMoments, instantiatePreset, PresetError, PRESETS } from '@lore/chronology/presets'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { revertProblem } from '@/core/history'
import {
  ApiError,
  type CalendarProposal,
  useApplyCalendarProposal,
  useCreateEntity,
  useDataSource,
  useEntity,
  useMutations,
  useProposeCalendarChange,
  useRevertChange,
  type Entity,
} from '@/data'

import { dimensionTime, type DimensionTime } from '../calendars'
import { ImpactPreviewDialog, type Strategy } from '../impact-preview'
import { SELECT_CLASS } from '../select'
import { useDimensionLenses } from '../time-context'
import {
  CyclesEditor,
  DefinitionPointField,
  ErasEditor,
  MarkersEditor,
  OverlaysEditor,
  RegimesEditor,
  type TimeScope,
} from './advanced'
import { DisplayEditor, FormatsEditor } from './formats'
import { blankDefinition, blocking, edit, regimeOf, regimePath, type Definition } from './model'
import { Converter, ErrorList, YearGrid } from './preview'
import { AlignmentEditor, LevelsEditor, TemplatesEditor, TopEditor } from './structure'

type Proposal = CalendarProposal

/** Compiles the draft with the TS engine: the calendar, or its problems (with JSON pointers). */
function compile(
  definition: unknown,
  dimension: DimensionTime,
  calendarId: string | null,
  stored: Record<string, string>,
): { calendar: CompiledCalendar | null; errors: ValidationError[] } {
  let resolved: Record<string, string> = stored
  try {
    resolved = { ...stored, ...absoluteMoments(definition as Definition) }
  } catch {
    // Not a definition yet: the validator says why.
  }
  const result = validateCalendar(definition, {
    calendar_id: calendarId,
    base_unit: dimension.baseUnit,
    dimension_duration: formatMoment(dimension.duration),
    resolved,
  })
  return Array.isArray(result)
    ? { calendar: null, errors: result }
    : { calendar: result, errors: [] }
}

/** Base units in the first day of the calendar (for the overlays' days helper), if it has days. */
function uniformDay(calendar: CompiledCalendar | null): bigint | null {
  if (calendar?.levels.includes('day') !== true) return null
  try {
    const { start, end } = unitBounds(calendar, 0n, 'day')
    return end - start
  } catch (error) {
    if (error instanceof DateError) return null
    throw error
  }
}

/** Why a save was refused, in words (and the definition's problems, if the server listed them). */
function saveProblem(error: unknown): { message: string; errors: ValidationError[] } {
  if (!(error instanceof ApiError))
    return { message: 'The calendar couldn’t be saved.', errors: [] }
  return {
    message: error.detail,
    errors: error.errors.map((item) => ({
      code: item.code,
      path: item.path.replace(/^(body\.)?(ext\.)?definition/, ''),
      message: item.message,
    })),
  }
}

/**
 * The other display calendars of the calendar's dimension, for time points in its definition. A
 * draft dimension (the wizard's) has none, and no events to anchor to.
 */
function useScope(
  vault: string,
  dimension: DimensionTime,
  calendarId: string | null,
  draft: boolean,
): TimeScope {
  const { lenses } = useDimensionLenses(vault, draft ? null : dimension.id)
  return useMemo(
    () => ({
      vault: draft ? null : vault,
      dimension,
      lenses: lenses.filter((lens) => lens.id !== calendarId),
    }),
    [vault, dimension, lenses, calendarId, draft],
  )
}

/** The structure editor, the JSON tab and the live preview around one draft definition. */
function Editor({
  vault,
  dimension,
  calendarId,
  initial,
  stored,
  header,
  saving,
  onSave,
  problem,
  draft = false,
  saveLabel,
}: {
  vault: string
  dimension: DimensionTime
  calendarId: string | null
  initial: Definition
  stored: Record<string, string>
  header: React.ReactNode
  saving: boolean
  onSave: (definition: Definition) => void
  problem: { message: string; errors: ValidationError[] } | null
  /** The dimension doesn't exist yet (the wizard's first calendar). */
  draft?: boolean
  saveLabel?: string
}) {
  const [definition, setDefinition] = useState(initial)
  const [json, setJson] = useState<string | null>(null)
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [tab, setTab] = useState('structure')
  const { calendar, errors } = useMemo(
    () => compile(definition, dimension, calendarId, stored),
    [definition, dimension, calendarId, stored],
  )
  const shown = [...errors, ...(problem?.errors ?? [])]
  const editable = useMutations() !== null
  const change = (next: Definition) => {
    setDefinition(next)
  }
  const scope = useScope(vault, dimension, calendarId, draft)
  const [regimeIndex, setRegimeIndex] = useState(0)
  const regime = Math.min(regimeIndex, definition.regimes.length - 1)
  const atPath = `${regimePath(regime)}/alignment/at`
  const atEditor = (
    <DefinitionPointField
      definition={definition}
      scope={scope}
      path={atPath}
      label="Begins at"
      local={false}
      value={regimeOf(definition, regime).alignment.at}
      onChange={(value) => {
        setDefinition((current) =>
          edit(current, (draft) => {
            // Without `local`, the field only yields time points of the dimension.
            regimeOf(draft, regime).alignment.at = value as TimePoint
          }),
        )
      }}
    />
  )
  const dayLength = useMemo(() => uniformDay(calendar), [calendar])
  const sampleAt = useMemo(() => dimension.duration / 2n, [dimension])
  const props = { definition, errors: shown, onChange: change, regimeIndex: regime }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-2">
        {header}
        <div className="flex-1" />
        {editable && (
          <Button
            disabled={saving || blocking(errors).length > 0 || jsonError !== null}
            onClick={() => {
              onSave(definition)
            }}
          >
            {saving ? 'Saving…' : (saveLabel ?? (calendarId === null ? 'Create calendar' : 'Save'))}
          </Button>
        )}
      </div>
      {problem !== null && (
        <p role="alert" className="text-sm text-destructive">
          {problem.message}
        </p>
      )}
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <Tabs
          value={tab}
          onValueChange={(next) => {
            if (next === 'json') setJson(JSON.stringify(definition, null, 2))
            setTab(next)
          }}
        >
          <TabsList>
            <TabsTrigger value="structure">Structure</TabsTrigger>
            <TabsTrigger value="json">JSON</TabsTrigger>
          </TabsList>
          <TabsContent value="structure" className="flex flex-col gap-6">
            <LevelsEditor {...props} />
            <RegimesEditor {...props} scope={scope} onSelect={setRegimeIndex} />
            <TemplatesEditor {...props} />
            <TopEditor {...props} />
            <AlignmentEditor {...props} atEditor={atEditor} />
            <CyclesEditor {...props} />
            <ErasEditor {...props} scope={scope} />
            <OverlaysEditor {...props} scope={scope} dayLength={dayLength} />
            <MarkersEditor {...props} />
            <FormatsEditor {...props} calendar={calendar} sampleAt={sampleAt} />
            <DisplayEditor {...props} />
          </TabsContent>
          <TabsContent value="json" className="flex flex-col gap-2">
            <Textarea
              aria-label="Definition JSON"
              data-path=""
              spellCheck={false}
              className="min-h-[32rem] font-mono text-xs"
              value={json ?? ''}
              onChange={(event) => {
                setJson(event.target.value)
                try {
                  setDefinition(JSON.parse(event.target.value) as Definition)
                  setJsonError(null)
                } catch (error) {
                  setJsonError(error instanceof Error ? error.message : 'Not JSON.')
                }
              }}
            />
            {jsonError !== null && (
              <p role="alert" className="text-sm text-destructive">
                Not valid JSON: {jsonError}
              </p>
            )}
          </TabsContent>
        </Tabs>
        <aside aria-label="Preview" className="flex flex-col gap-4">
          <h2 className="text-sm font-semibold">Preview</h2>
          <ErrorList errors={shown} />
          {calendar !== null && <YearGrid calendar={calendar} />}
          {calendar !== null && <Converter calendar={calendar} dimension={dimension} />}
          <p className="text-xs text-muted-foreground">
            Checked by the same engine as the server, in your browser, on every change.
          </p>
          {!draft && (
            <Link
              to="/v/$vault/d/$dimension"
              params={{ vault, dimension: dimension.id }}
              className="text-sm underline"
            >
              Back to {dimension.name}
            </Link>
          )}
        </aside>
      </div>
    </div>
  )
}

function useDimension(vault: string, id: string | null) {
  const entity = useEntity(vault, id ?? '', {}, { enabled: id !== null })
  return entity.data === undefined ? null : dimensionTime(entity.data)
}

/** A proposal open in the impact preview, and how the server answered its last apply. */
interface Review {
  proposal: Proposal
  definition: Definition
  stale: boolean
  problems: Record<string, string>
  message: string | null
}

/** Per item key, why the server refused its strategy (`422 proposal_unresolved`). */
function itemProblems(error: ApiError): Record<string, string> {
  return Object.fromEntries(
    error.errors
      .filter((item) => item.path.startsWith('strategies.'))
      .map((item) => [item.path.slice('strategies.'.length), item.message]),
  )
}

/**
 * The calendar editor (`/v/$vault/calendars/$calendar/edit`, frontend.md §8, #76, #77): the
 * definition's structure (levels, rules and reforms, templates, the year pattern with exceptions,
 * the alignment, cycles, eras, overlays, formats and display options), a JSON tab, and a live
 * preview by the TS engine (problems that focus their field, a year of the calendar, a converter).
 * Saving previews the change on the server first (a proposal, D1): when nothing moves it applies
 * at once; otherwise the impact preview lists what moves or breaks and the author picks a
 * strategy per record. Applying is one changeset, undoable from the toast.
 */
export function CalendarEditor({ vault, calendarId }: { vault: string; calendarId: string }) {
  const entity = useEntity(vault, calendarId)
  const ext = (entity.data?.ext ?? null) as {
    definition?: Definition
    resolved_anchors?: Record<string, string>
  } | null
  const dimension = useDimension(vault, entity.data?.dimension_id ?? null)
  if (entity.isPending || (entity.data !== undefined && dimension === null)) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  }
  if (entity.data?.kind !== 'calendar' || ext?.definition === undefined || dimension === null) {
    return <p className="p-6 text-sm text-muted-foreground">This calendar can’t be edited.</p>
  }
  return (
    <ExistingCalendar
      vault={vault}
      calendar={entity.data}
      definition={ext.definition}
      stored={ext.resolved_anchors ?? {}}
      dimension={dimension}
    />
  )
}

function ExistingCalendar({
  vault,
  calendar,
  definition,
  stored,
  dimension,
}: {
  vault: string
  calendar: Entity
  definition: Definition
  stored: Record<string, string>
  dimension: DimensionTime
}) {
  const propose = useProposeCalendarChange(vault)
  const apply = useApplyCalendarProposal(vault)
  const revert = useRevertChange(vault)
  const source = useDataSource()
  const [problem, setProblem] = useState<ReturnType<typeof saveProblem> | null>(null)
  const [review, setReview] = useState<Review | null>(null)

  const undo = async () => {
    const { items } = await source.changes(vault, { limit: 20 })
    const last = items.find(
      (item) =>
        item.reverted_by_changeset_id === null && item.summary.startsWith('Edited the calendar'),
    )
    if (last === undefined) return
    try {
      await revert.mutateAsync(last.id)
      toast.success(`Undone: ${last.summary}`)
    } catch (error) {
      const refused = revertProblem(error)
      toast.error('Couldn’t undo the calendar change', {
        description: [refused.message, ...refused.details].join(' '),
      })
    }
  }

  const applyProposal = (proposal: Proposal, strategies: Record<string, Strategy>) => {
    apply.mutate(
      { calendar: calendar.id, proposal: proposal.id, body: { strategies } },
      {
        onSuccess: (result) => {
          setReview(null)
          const moved = result.kept + result.pinned + result.constrained + result.accepted
          toast.success(
            moved === 0
              ? 'Calendar saved'
              : `Calendar saved: ${moved} ${moved === 1 ? 'time point' : 'time points'} updated`,
            {
              action: {
                label: 'Undo',
                onClick: () => {
                  void undo()
                },
              },
            },
          )
        },
        onError: (error) => {
          if (!(error instanceof ApiError)) {
            setReview(
              (current) => current && { ...current, message: 'The change couldn’t be applied.' },
            )
            return
          }
          if (error.status === 404 || error.code === 'proposal_stale') {
            setReview((current) => current && { ...current, stale: true, message: null })
          } else if (error.code === 'proposal_unresolved') {
            setReview(
              (current) =>
                current && { ...current, problems: itemProblems(error), message: error.detail },
            )
          } else if (review === null) {
            setProblem(saveProblem(error))
          } else {
            setReview((current) => current && { ...current, message: error.detail })
          }
        },
      },
    )
  }

  const save = (next: Definition) => {
    setProblem(null)
    propose.mutate(
      { calendar: calendar.id, definition: next },
      {
        onSuccess: (proposal) => {
          if (proposal.items.length === 0 && proposal.series.length === 0) {
            applyProposal(proposal, {})
          } else {
            setReview({ proposal, definition: next, stale: false, problems: {}, message: null })
          }
        },
        onError: (error) => {
          setReview(null)
          setProblem(saveProblem(error))
        },
      },
    )
  }

  return (
    <>
      <Editor
        key={`${calendar.id}:${calendar.revision}`}
        vault={vault}
        dimension={dimension}
        calendarId={calendar.id}
        initial={definition}
        stored={stored}
        header={<h1 className="text-2xl font-semibold">{calendar.name}</h1>}
        saving={propose.isPending || apply.isPending}
        problem={problem}
        onSave={save}
      />
      {review !== null && (
        <ImpactPreviewDialog
          key={review.proposal.id}
          vault={vault}
          proposal={review.proposal}
          applying={apply.isPending}
          stale={review.stale}
          problems={review.problems}
          message={review.message}
          onApply={(strategies) => {
            applyProposal(review.proposal, strategies)
          }}
          onRerun={() => {
            save(review.definition)
          }}
          onClose={() => {
            setReview(null)
          }}
        />
      )}
    </>
  )
}

/** Where a new calendar starts: blank, or a preset (in seconds). */
function starting(preset: string): Definition {
  const found = PRESETS.get(preset)
  return found === undefined ? blankDefinition() : instantiatePreset(found, { num: 1n, den: 1n })
}

/** A new calendar of a dimension (`/v/$vault/calendars/new?dimension=…`), blank or from a preset. */
export function NewCalendar({ vault, dimensionId }: { vault: string; dimensionId: string }) {
  const dimension = useDimension(vault, dimensionId)
  const navigate = useNavigate()
  const create = useCreateEntity(vault)
  const [name, setName] = useState('')
  const [preset, setPreset] = useState('')
  const [problem, setProblem] = useState<ReturnType<typeof saveProblem> | null>(null)
  if (dimension === null) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  const header = (
    <div className="flex flex-wrap items-center gap-2">
      <h1 className="text-2xl font-semibold">New calendar</h1>
      <Input
        aria-label="Calendar name"
        placeholder="Name"
        className="h-9 w-56"
        value={name}
        onChange={(event) => {
          setName(event.target.value)
        }}
      />
      <select
        aria-label="Start from"
        className={SELECT_CLASS}
        value={preset}
        onChange={(event) => {
          setPreset(event.target.value)
          const found = PRESETS.get(event.target.value)
          if (found !== undefined && name === '') setName(found.name)
        }}
      >
        <option value="">Blank</option>
        {[...PRESETS.values()].map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </div>
  )
  return (
    <Editor
      key={preset}
      vault={vault}
      dimension={dimension}
      calendarId={null}
      initial={starting(preset)}
      stored={{}}
      header={header}
      saving={create.isPending}
      problem={problem}
      onSave={(definition) => {
        setProblem(null)
        create.mutate(
          {
            kind: 'calendar',
            name: name.trim() || 'Calendar',
            dimension_id: dimensionId,
            ext: { definition },
          },
          {
            onSuccess: (result: { entity: Entity }) => {
              void navigate({
                to: '/v/$vault/calendars/$calendar/edit',
                params: { vault, calendar: result.entity.id },
              })
            },
            onError: (error) => {
              setProblem(saveProblem(error))
            },
          },
        )
      }}
    />
  )
}

/**
 * The first calendar of a dimension the wizard hasn't created yet (#379): the editor on the
 * wizard's base unit and duration, blank or from a preset scaled to that base unit. Nothing is
 * saved here: **Use this calendar** hands the definition back to the wizard, which creates the
 * dimension with it.
 */
export function DraftCalendar({
  vault,
  dimension,
  secondsPerBaseUnit,
  initial,
  startFrom,
  onDone,
  onCancel,
}: {
  vault: string
  dimension: DimensionTime
  secondsPerBaseUnit: { num: bigint; den: bigint }
  /** The definition designed so far (`null`: start from `startFrom`). */
  initial: Definition | null
  /** A preset id, or `''` for a blank calendar. */
  startFrom: string
  onDone: (definition: Definition) => void
  onCancel: () => void
}) {
  const start = useMemo(() => {
    if (initial !== null) return { definition: initial, problem: null }
    const found = PRESETS.get(startFrom)
    if (found === undefined) return { definition: blankDefinition(), problem: null }
    try {
      return { definition: instantiatePreset(found, secondsPerBaseUnit), problem: null }
    } catch (error) {
      if (!(error instanceof PresetError)) throw error
      return { definition: null, problem: `${found.name} doesn’t fit this base unit.` }
    }
  }, [initial, startFrom, secondsPerBaseUnit])
  const cancel = (
    <Button type="button" variant="outline" onClick={onCancel}>
      Cancel
    </Button>
  )
  if (start.definition === null) {
    return (
      <div className="flex flex-col items-start gap-3 p-6">
        <p role="alert" className="text-sm text-destructive">
          {start.problem}
        </p>
        {cancel}
      </div>
    )
  }
  return (
    <Editor
      vault={vault}
      dimension={dimension}
      calendarId={null}
      initial={start.definition}
      stored={{}}
      header={
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold">Design the first calendar</h2>
          {cancel}
        </div>
      }
      saving={false}
      problem={null}
      draft
      saveLabel="Use this calendar"
      onSave={onDone}
    />
  )
}
