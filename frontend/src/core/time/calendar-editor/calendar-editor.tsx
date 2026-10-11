import {
  type CompiledCalendar,
  type ValidationError,
  formatMoment,
  validateCalendar,
} from '@lore/chronology'
import { absoluteMoments, instantiatePreset, PRESETS } from '@lore/chronology/presets'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  useCreateEntity,
  useEntity,
  useMutations,
  useUpdateLatest,
  type Entity,
} from '@/data'

import { BigNumberInput } from '../big-number-input'
import { dimensionTime, type DimensionTime } from '../calendars'
import { SELECT_CLASS } from '../select'
import { blankDefinition, blocking, type Definition } from './model'
import { Converter, ErrorList, YearGrid } from './preview'
import { AlignmentEditor, LevelsEditor, TemplatesEditor, TopEditor } from './structure'

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

/** Why a save was refused, in words (and the definition's problems, if the server listed them). */
function saveProblem(error: unknown): { message: string; errors: ValidationError[] } {
  if (!(error instanceof ApiError))
    return { message: 'The calendar couldn’t be saved.', errors: [] }
  const dependents = error.context.dependents
  if (error.status === 409 && typeof dependents === 'number') {
    return {
      message: `${formatMoment(BigInt(dependents))} time points depend on this calendar: changing it goes through a proposal with an impact preview (calendar editor II, #77).`,
      errors: [],
    }
  }
  return {
    message: error.detail,
    errors: error.errors.map((item) => ({
      code: item.code,
      path: item.path.replace(/^(body\.)?ext\.definition/, ''),
      message: item.message,
    })),
  }
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
  const at = definition.regimes[0].alignment.at
  const atEditor =
    at.anchor.kind === 'absolute' ? (
      <div className="flex flex-col gap-1 text-xs">
        Begins at (t)
        <BigNumberInput
          aria-label="Alignment moment"
          value={BigInt(at.anchor.t)}
          min={0n}
          max={dimension.duration}
          onChange={(t) => {
            if (t === null) return
            setDefinition((current) => {
              const next = structuredClone(current)
              next.regimes[0].alignment.at = {
                ...at,
                anchor: { kind: 'absolute', t: formatMoment(t) },
              }
              return next
            })
          }}
        />
      </div>
    ) : (
      <p className="text-xs text-muted-foreground">
        Begins at a {at.anchor.kind} time point: edit it in the JSON tab.
      </p>
    )
  const extraRegimes = definition.regimes.length > 1

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
            {saving ? 'Saving…' : calendarId === null ? 'Create calendar' : 'Save'}
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
            {extraRegimes && (
              <p className="text-sm text-muted-foreground">
                This calendar has calendar reforms: the forms show the first set of rules; edit the
                others in the JSON tab.
              </p>
            )}
            <LevelsEditor definition={definition} errors={shown} onChange={change} />
            <TemplatesEditor definition={definition} errors={shown} onChange={change} />
            <TopEditor definition={definition} errors={shown} onChange={change} />
            <AlignmentEditor
              definition={definition}
              errors={shown}
              onChange={change}
              atEditor={atEditor}
            />
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
          <Link
            to="/v/$vault/d/$dimension"
            params={{ vault, dimension: dimension.id }}
            className="text-sm underline"
          >
            Back to {dimension.name}
          </Link>
        </aside>
      </div>
    </div>
  )
}

function useDimension(vault: string, id: string | null) {
  const entity = useEntity(vault, id ?? '', {}, { enabled: id !== null })
  return entity.data === undefined ? null : dimensionTime(entity.data)
}

/**
 * The calendar editor (`/v/$vault/calendars/$calendar/edit`, frontend.md §8, #76): the
 * definition's structure (levels, templates, the year pattern with exceptions, the alignment), a
 * JSON tab, and a live preview by the TS engine (problems that focus their field, a year of the
 * calendar, a converter). Saving goes straight to the server when nothing depends on the
 * calendar; otherwise the server asks for a proposal, which #77 handles.
 */
export function CalendarEditor({ vault, calendarId }: { vault: string; calendarId: string }) {
  const entity = useEntity(vault, calendarId)
  const ext = (entity.data?.ext ?? null) as {
    definition?: Definition
    resolved_anchors?: Record<string, string>
  } | null
  const dimension = useDimension(vault, entity.data?.dimension_id ?? null)
  const update = useUpdateLatest(vault, { toast: false })
  const [problem, setProblem] = useState<ReturnType<typeof saveProblem> | null>(null)
  if (entity.isPending || (entity.data !== undefined && dimension === null)) {
    return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  }
  if (entity.data?.kind !== 'calendar' || ext?.definition === undefined || dimension === null) {
    return <p className="p-6 text-sm text-muted-foreground">This calendar can’t be edited.</p>
  }
  return (
    <Editor
      key={`${calendarId}:${entity.data.revision}`}
      vault={vault}
      dimension={dimension}
      calendarId={calendarId}
      initial={ext.definition}
      stored={ext.resolved_anchors ?? {}}
      header={<h1 className="text-2xl font-semibold">{entity.data.name}</h1>}
      saving={update.isPending}
      problem={problem}
      onSave={(definition) => {
        setProblem(null)
        update.mutate(
          { id: calendarId, change: { ext: { definition } } },
          {
            onError: (error) => {
              setProblem(saveProblem(error))
            },
          },
        )
      }}
    />
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
