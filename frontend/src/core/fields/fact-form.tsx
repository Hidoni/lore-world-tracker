import type { TimePoint } from '@lore/chronology'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  BoundsEditor,
  TimePointPicker,
  useDimensionLenses,
  useTimeContext,
  type Bounds,
} from '@/core/time'
import {
  ApiError,
  fieldErrors,
  useCreateFact,
  useEntity,
  useQuickSearch,
  useSaveOverride,
  useUpdateFact,
  type components,
  type Fact,
  type WireTimePoint,
} from '@/data'

import { FieldEditor } from './editors'
import { normalizeField, validateField, type FieldDef } from './schema'

type Visibility = components['schemas']['Visibility']

export const EXISTS = 'core.exists'
export const NAME = 'core.name'

const SELECT_CLASS = 'h-9 rounded-md border bg-transparent px-2 text-sm'

/** The source event of a fact: searched by name among events (`/search/quick`). */
function SourceEvent({
  vault,
  value,
  onChange,
}: {
  vault: string
  value: { id: string; name: string } | null
  onChange: (value: { id: string; name: string } | null) => void
}) {
  const id = useId()
  const [query, setQuery] = useState('')
  const q = query.trim()
  const results = useQuickSearch(vault, { q, kind: ['event'] })
  const hits = q === '' ? [] : (results.data?.items ?? [])
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
          Remove
        </Button>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1">
      <Input
        id={id}
        aria-label="Caused by (search events)"
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
                  setQuery('')
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

/** The name of the fact's source event (loaded by id). */
function useSourceName(vault: string, id: string | null): string {
  const event = useEntity(vault, id ?? '', {}, { enabled: id !== null })
  return event.data?.name ?? 'Event'
}

/**
 * Add or edit one fact (time-model.md §10.2-§10.4): a temporal field's value, an existence
 * period (`core.exists`) or a name (`core.name`), valid in a period of the entity's dimension's
 * timeline (the time context's when it is that dimension, else the dimension's prime), with an
 * optional source event, note and visibility.
 */
export function FactForm({
  vault,
  entity,
  fieldKey,
  field,
  fact,
  labels,
  onDone,
  onCancel,
}: {
  vault: string
  entity: { id: string; kind: string; dimension_id: string | null }
  fieldKey: string
  /** The temporal field (`undefined` for existence and names). */
  field?: FieldDef
  /** The fact being edited (`undefined`: a new one). */
  fact?: Fact
  /** The bounds' labels ("Born"/"Died" for a character's existence). */
  labels?: { from: string; to: string }
  onDone: () => void
  onCancel: () => void
}) {
  const id = useId()
  const context = useTimeContext(vault)
  const dimensionId = entity.dimension_id ?? context.dimensionId
  const { dimension } = useDimensionLenses(vault, dimensionId)
  const timeline =
    fact?.timeline_id ??
    (dimensionId === context.dimensionId ? context.timelineId : dimension?.primeTimelineId) ??
    null
  const create = useCreateFact(vault)
  const update = useUpdateFact(vault)
  const mutation = fact === undefined ? create : update
  const errors = fieldErrors(mutation.error)
  const [value, setValue] = useState<unknown>(fact?.value ?? (fieldKey === EXISTS ? true : null))
  const [bounds, setBounds] = useState<Bounds>({
    from: (fact?.valid_from ?? null) as TimePoint | null,
    to: (fact?.valid_to ?? null) as TimePoint | null,
  })
  const sourceName = useSourceName(vault, fact?.source_event_id ?? null)
  const [source, setSource] = useState<{ id: string; name: string } | null>(
    fact?.source_event_id == null ? null : { id: fact.source_event_id, name: sourceName },
  )
  const [note, setNote] = useState(fact?.note ?? '')
  const [visibility, setVisibility] = useState<Visibility>(fact?.visibility ?? 'public')
  const problem =
    field === undefined ? null : value === null ? 'Enter a value.' : validateField(field, value)

  const submit = (): void => {
    if (problem !== null || timeline === null) return
    const body = {
      ...(fieldKey === EXISTS ? {} : { value: field ? normalizeField(field, value) : value }),
      valid_from: bounds.from as WireTimePoint | null,
      valid_to: bounds.to as WireTimePoint | null,
      source_event_id: source?.id ?? null,
      note: note.trim() === '' ? null : note.trim(),
      visibility,
    }
    if (fact === undefined) {
      create.mutate(
        { entity: entity.id, body: { ...body, field_key: fieldKey, timeline_id: timeline } },
        { onSuccess: onDone },
      )
    } else {
      update.mutate(
        { id: fact.id, body: { ...body, revision: fact.revision } },
        { onSuccess: onDone },
      )
    }
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-md border p-3"
      aria-label={fact === undefined ? 'New value' : 'Edit value'}
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      {fieldKey === NAME && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-name`}>Name</Label>
          <Input
            id={`${id}-name`}
            value={typeof value === 'string' ? value : ''}
            maxLength={500}
            onChange={(event) => {
              setValue(event.target.value === '' ? null : event.target.value)
            }}
          />
        </div>
      )}
      {field !== undefined && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-value`}>{field.label}</Label>
          <FieldEditor
            field={field}
            id={`${id}-value`}
            value={value}
            invalid={problem !== null && value !== null}
            onChange={setValue}
            onCommit={() => undefined}
            onCancel={onCancel}
          />
          {(errors.value ?? (value !== null ? problem : null)) && (
            <p className="text-sm text-destructive">{errors.value ?? problem}</p>
          )}
        </div>
      )}
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">Valid</legend>
        <BoundsEditor
          vault={vault}
          dimensionId={dimensionId}
          value={bounds}
          onChange={setBounds}
          {...(labels === undefined ? {} : { labels })}
        />
        {(errors.valid_from ?? errors.valid_to) !== undefined && (
          <p className="text-sm text-destructive">{errors.valid_from ?? errors.valid_to}</p>
        )}
      </fieldset>
      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Caused by</span>
        <SourceEvent vault={vault} value={source} onChange={setSource} />
      </div>
      <div className="grid grid-cols-[1fr_auto] gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-note`}>Note</Label>
          <Input
            id={`${id}-note`}
            value={note}
            maxLength={5000}
            onChange={(event) => {
              setNote(event.target.value)
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-visibility`}>Visibility</Label>
          <select
            id={`${id}-visibility`}
            className={SELECT_CLASS}
            value={visibility}
            onChange={(event) => {
              setVisibility(event.target.value as Visibility)
            }}
          >
            <option value="public">Public</option>
            <option value="spoiler">Spoiler</option>
            <option value="private">Private</option>
          </select>
        </div>
      </div>
      {timeline === null && (
        <p className="text-sm text-destructive">
          A multiversal entity’s values need a dimension: choose one in the top bar.
        </p>
      )}
      {mutation.error && Object.keys(errors).length === 0 && (
        <p role="alert" className="text-sm text-destructive">
          {mutation.error.message}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={mutation.isPending || problem !== null || timeline === null}
        >
          {fact === undefined ? 'Add' : 'Save'}
        </Button>
      </div>
    </form>
  )
}

/**
 * Edit a fact in a branch (time-model.md §4.4): an inherited value still valid at the branch point
 * (or the branch's override of one) may change its value, when it stops being valid and its note.
 * Its start is the shared past. Saving creates or updates the branch's override of `rootId`.
 */
export function OverrideFactForm({
  vault,
  entity,
  fieldKey,
  field,
  fact,
  rootId,
  timelineId,
  branchName,
  labels,
  onDone,
  onCancel,
}: {
  vault: string
  entity: { id: string; kind: string; dimension_id: string | null }
  fieldKey: string
  field?: FieldDef
  /** The fact as the branch sees it (the inherited one, or the branch's override). */
  fact: Fact
  /** The inherited fact being overridden. */
  rootId: string
  timelineId: string
  branchName: string | null
  labels?: { from: string; to: string }
  onDone: () => void
  onCancel: () => void
}) {
  const id = useId()
  const context = useTimeContext(vault)
  const dimensionId = entity.dimension_id ?? context.dimensionId
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const save = useSaveOverride(vault)
  const [value, setValue] = useState<unknown>(fact.value)
  const [until, setUntil] = useState<TimePoint | null>((fact.valid_to ?? null) as TimePoint | null)
  const [note, setNote] = useState(fact.note ?? '')
  const problem =
    field === undefined ? null : value === null ? 'Enter a value.' : validateField(field, value)
  const failure =
    save.error === null
      ? null
      : save.error instanceof ApiError
        ? (save.error.errors[0]?.message ?? save.error.detail)
        : save.error.message

  const submit = (): void => {
    if (problem !== null) return
    const changes: Record<string, unknown> = {
      valid_to: until,
      note: note.trim() === '' ? null : note.trim(),
    }
    if (fieldKey !== EXISTS) changes.value = field ? normalizeField(field, value) : value
    save.mutate({ recordType: 'fact', rootId, timelineId, changes }, { onSuccess: onDone })
  }

  return (
    <form
      className="flex flex-col gap-3 rounded-md border border-dashed p-3"
      aria-label="Edit in this timeline"
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <p className="text-sm text-muted-foreground">
        Only {branchName ?? 'this branch'} changes. When this value starts is shared history, so
        only {fieldKey === EXISTS ? 'when it ends' : 'the value and when it ends'} can differ.
      </p>
      {fieldKey === NAME && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-name`}>Name</Label>
          <Input
            id={`${id}-name`}
            value={typeof value === 'string' ? value : ''}
            maxLength={500}
            onChange={(event) => {
              setValue(event.target.value === '' ? null : event.target.value)
            }}
          />
        </div>
      )}
      {field !== undefined && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-value`}>{field.label}</Label>
          <FieldEditor
            field={field}
            id={`${id}-value`}
            value={value}
            invalid={problem !== null && value !== null}
            onChange={setValue}
            onCommit={() => undefined}
            onCancel={onCancel}
          />
          {problem !== null && value !== null && (
            <p className="text-sm text-destructive">{problem}</p>
          )}
        </div>
      )}
      {dimension !== null && (
        <TimePointPicker
          vault={vault}
          dimension={dimension}
          lenses={lenses}
          value={until}
          onChange={setUntil}
          label={labels?.to ?? 'Until'}
        />
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-note`}>Note</Label>
        <Input
          id={`${id}-note`}
          value={note}
          maxLength={5000}
          onChange={(event) => {
            setNote(event.target.value)
          }}
        />
      </div>
      {failure !== null && (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={save.isPending || problem !== null}>
          Save in this timeline
        </Button>
      </div>
    </form>
  )
}
