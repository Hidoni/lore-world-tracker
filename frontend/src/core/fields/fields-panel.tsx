import { ChevronDownIcon, HistoryIcon, PencilIcon } from 'lucide-react'
import { Suspense, useId, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useExtensionRecord } from '@/core/modules'
import { fieldErrors, isRevisionConflict, type components, type Entity } from '@/data'
import { LazyRichTextEditor, isDoc, type SaveOutcome } from '@/editor'
import { readStored, writeStored } from '@/lib/storage'

import { FieldDisplay, FieldEditor, PLACEHOLDER_TYPES } from './editors'
import { FactHistory } from './fact-history'
import { normalizeField, validateField, type FieldDef } from './schema'

type Visibility = components['schemas']['Visibility']
interface Change {
  fields?: Record<string, unknown>
  field_visibility?: Record<string, Visibility | null>
}
type Saver = (change: Change) => Promise<{ ok: true } | { ok: false; error: unknown }>

/** A temporal field at the time cursor (time-model.md §10.5), from `GET …/state`. */
export interface AsOfField {
  /** The value then (a fact's, else the static one). */
  value: unknown
  /** From a fact covering the moment (else the static value). */
  fromFact: boolean
  /** The moment is inside a bound's uncertainty extent. */
  possible: boolean
  /** Several facts cover the moment (the latest start wins). */
  ambiguous: boolean
  /** How many facts the field has (its history). */
  changes: number
}

const IMMEDIATE = new Set(['boolean', 'enum', 'multi_enum'])
const GENERAL = 'General'

/** Core types with built-in editors (a module renderer only replaces how they are shown). */
const EDITABLE: Record<string, true> = Object.fromEntries(
  [
    'text',
    'long_text',
    'rich_text',
    'integer',
    'decimal',
    'boolean',
    'enum',
    'multi_enum',
    'url',
    'color',
    'measurement',
  ].map((type) => [type, true]),
)

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

function collapsedKey(kind: string): string {
  return `lore.collapsedSections.${kind}`
}

function readCollapsed(kind: string): string[] {
  try {
    const parsed = JSON.parse(readStored(collapsedKey(kind)) ?? '[]') as unknown
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string')
      : []
  } catch {
    return []
  }
}

/**
 * A `rich_text` field in the TipTap editor: it autosaves through the panel's saver (marks such as
 * entity links survive); "Done" closes it, saving what's left.
 */
function RichTextField({
  vault,
  field,
  value,
  save,
  onError,
  onDone,
}: {
  vault: string
  field: FieldDef
  value: unknown
  save: Saver
  onError: (message: string | null) => void
  onDone: () => void
}) {
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="w-full">
        <Suspense fallback={<p className="text-sm text-muted-foreground">Loading the editor…</p>}>
          <LazyRichTextEditor
            vault={vault}
            initial={isDoc(value) ? value : null}
            label={field.label}
            save={async (doc): Promise<SaveOutcome> => {
              const problem = validateField(field, doc)
              onError(problem)
              if (problem !== null) return 'failed'
              const result = await save({ fields: { [field.key]: normalizeField(field, doc) } })
              if (result.ok) return 'saved'
              if (isRevisionConflict(result.error)) return 'conflict'
              const errors = fieldErrors(result.error)
              onError(errors[`fields.${field.key}`] ?? errors.fields ?? null)
              return 'failed'
            }}
          />
        </Suspense>
      </div>
      <Button variant="outline" size="sm" onClick={onDone}>
        Done
      </Button>
    </div>
  )
}

/**
 * A temporal field's value at the time cursor: muted with an explanation when only possible, and
 * the static (timeless) value it stands in for.
 */
function AsOfValue({
  vault,
  field,
  asOf,
  staticValue,
}: {
  vault: string
  field: FieldDef
  asOf: AsOfField
  staticValue: unknown
}) {
  const notes = [
    asOf.possible ? 'Possibly: the moment is inside an uncertain date of this value.' : null,
    asOf.ambiguous ? 'Several values overlap here; the latest one is shown.' : null,
  ].filter((note): note is string => note !== null)
  return (
    <div className="flex min-h-9 flex-col justify-center text-sm">
      <span
        className={asOf.possible ? 'text-muted-foreground italic' : undefined}
        title={notes.length > 0 ? notes.join(' ') : undefined}
        data-certainty={asOf.possible ? 'possible' : 'certain'}
      >
        <FieldDisplay vault={vault} field={field} value={asOf.value} />
        {notes.length > 0 && <span className="sr-only"> ({notes.join(' ')})</span>}
      </span>
      {staticValue !== null && staticValue !== undefined && staticValue !== '' && (
        <span className="text-xs text-muted-foreground">
          Timeless value: <FieldDisplay vault={vault} field={field} value={staticValue} />
        </span>
      )}
    </div>
  )
}

function FieldRow({
  vault,
  kind,
  field,
  value,
  visibility,
  editable,
  save,
  asOf,
  history,
}: {
  vault: string
  kind: string
  field: FieldDef
  value: unknown
  visibility: Visibility | undefined
  editable: boolean
  save: Saver
  asOf?: AsOfField
  /** Temporal fields: the history toggle. */
  history?: { open: boolean; toggle: () => void }
}) {
  const id = useId()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const renderers = useExtensionRecord('fieldTypeRenderers', vault)
  const Renderer = renderers[field.type]
  const ModuleEditor = useExtensionRecord('fieldTypeEditors', vault)[field.type]
  // Core types have editors; module types bring their own (media, `fieldTypeEditors`).
  const canEditType =
    editable &&
    ((Object.hasOwn(EDITABLE, field.type) && !PLACEHOLDER_TYPES.has(field.type)) ||
      ModuleEditor !== undefined)
  const immediate = IMMEDIATE.has(field.type)
  // Lists of rich text have no editor yet: shown, not edited.
  const rich = field.type === 'rich_text'
  const canEdit = canEditType && !(rich && field.multiple)

  const commit = async (next: unknown = draft): Promise<void> => {
    if (inFlight.current) return
    if (sameValue(next, value)) {
      setEditing(false)
      setError(null)
      return
    }
    const problem = validateField(field, next)
    if (problem !== null) {
      setDraft(next)
      setError(problem)
      return
    }
    inFlight.current = true
    const result = await save({ fields: { [field.key]: normalizeField(field, next) } })
    inFlight.current = false
    if (result.ok) {
      setEditing(false)
      setError(null)
      return
    }
    if (isRevisionConflict(result.error)) {
      // The conflict dialog holds the change now (overwrite, copy or drop it).
      setEditing(false)
      return
    }
    const errors = fieldErrors(result.error)
    const message = errors[`fields.${field.key}`] ?? errors.fields
    if (message !== undefined) setError(message)
  }

  const start = (): void => {
    setDraft(value)
    setError(null)
    setEditing(true)
  }

  const showEditor = canEdit && (editing || immediate)

  return (
    <div className="grid grid-cols-[10rem_1fr_auto] items-start gap-x-3 gap-y-1 py-1.5">
      <label htmlFor={id} className="pt-1.5 text-sm text-muted-foreground">
        {field.label}
        {field.required && <span aria-hidden> *</span>}
      </label>
      <div className="flex min-w-0 flex-col gap-1">
        {showEditor && rich ? (
          <RichTextField
            vault={vault}
            field={field}
            value={value}
            save={save}
            onError={setError}
            onDone={() => {
              setEditing(false)
            }}
          />
        ) : showEditor && ModuleEditor !== undefined ? (
          <ModuleEditor
            vault={vault}
            field={field}
            id={id}
            value={draft}
            invalid={error !== null}
            onChange={setDraft}
            onCommit={(next) => {
              void commit(next === undefined ? draft : next)
            }}
            onCancel={() => {
              setEditing(false)
              setError(null)
            }}
          />
        ) : showEditor ? (
          <FieldEditor
            field={field}
            id={id}
            suggest={{ vault, kind }}
            value={immediate && !editing ? value : draft}
            invalid={error !== null}
            onChange={setDraft}
            onCommit={(next) => {
              void commit(next === undefined ? draft : next)
            }}
            onCancel={() => {
              setEditing(false)
              setError(null)
            }}
          />
        ) : asOf?.fromFact === true ? (
          <AsOfValue vault={vault} field={field} asOf={asOf} staticValue={value} />
        ) : (
          <div className="flex min-h-9 items-center text-sm">
            {Renderer !== undefined ? (
              <Renderer vault={vault} fieldKey={field.key} value={value} />
            ) : (
              <FieldDisplay vault={vault} field={field} value={value} />
            )}
          </div>
        )}
        {asOf !== undefined && asOf.changes > 0 && (
          <p className="text-xs text-muted-foreground">
            Changed {asOf.changes === 1 ? 'once' : `${String(asOf.changes)} times`} over time
          </p>
        )}
        {error !== null && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {field.help && <p className="text-xs text-muted-foreground">{field.help}</p>}
      </div>
      <div className="flex items-center gap-1">
        {history !== undefined && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`${field.label} over time`}
            aria-expanded={history.open}
            title="Values over time"
            onClick={history.toggle}
          >
            <HistoryIcon />
          </Button>
        )}
        {canEdit && !immediate && !editing && (
          <Button variant="ghost" size="icon" aria-label={`Edit ${field.label}`} onClick={start}>
            <PencilIcon />
          </Button>
        )}
        {editable && (
          <select
            aria-label={`${field.label} visibility`}
            className="h-8 rounded-md border bg-transparent px-1 text-xs"
            value={visibility ?? ''}
            onChange={(event) => {
              const next = event.target.value === '' ? null : (event.target.value as Visibility)
              void save({ field_visibility: { [field.key]: next } })
            }}
          >
            <option value="">Default ({field.default_visibility})</option>
            <option value="public">Public</option>
            <option value="spoiler">Spoiler</option>
            <option value="private">Private</option>
          </select>
        )}
        {!editable && visibility !== undefined && visibility !== 'public' && (
          <span className="text-xs text-muted-foreground">{visibility}</span>
        )}
      </div>
    </div>
  )
}

/**
 * The fields panel (frontend.md §7): the kind's fields grouped by `section` (collapsible,
 * remembered per kind), each shown by its type's renderer (or a module's `fieldTypeRenderers`)
 * and edited inline: text saves on Enter or blur, choices at once, rich text in the editor
 * (autosaved). Values are checked against
 * the field definitions before saving; the per-field visibility select sets an override. With
 * `asOf` (the time cursor), temporal fields show their value then and how often they changed;
 * editing still changes the timeless value.
 */
export function FieldsPanel({
  vault,
  entity,
  fields,
  editable,
  save,
  asOf,
}: {
  vault: string
  entity: Entity
  fields: readonly FieldDef[]
  editable: boolean
  save: Saver
  /** Temporal fields at the time cursor, by key (none in all-time mode). */
  asOf?: Record<string, AsOfField>
}) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(entity.kind))
  const [historyOf, setHistoryOf] = useState<string | null>(null)
  const live = fields
    .filter((field) => !field.archived)
    .toSorted((a, b) => a.sort - b.sort || a.label.localeCompare(b.label))
  if (live.length === 0)
    return <p className="text-sm text-muted-foreground">This kind has no fields.</p>

  const sections = new Map<string, FieldDef[]>()
  for (const field of live) {
    const name = field.section ?? GENERAL
    sections.set(name, [...(sections.get(name) ?? []), field])
  }
  const values = entity.fields as Record<string, unknown>
  const overrides = entity.field_visibility as Record<string, Visibility | undefined>
  const toggle = (name: string): void => {
    const next = collapsed.includes(name)
      ? collapsed.filter((other) => other !== name)
      : [...collapsed, name]
    setCollapsed(next)
    writeStored(collapsedKey(entity.kind), JSON.stringify(next))
  }

  return (
    <div className="flex flex-col gap-2">
      {[...sections].map(([name, members]) => {
        const open = !collapsed.includes(name)
        return (
          <section key={name} aria-label={name}>
            {sections.size > 1 && (
              <button
                type="button"
                className="flex items-center gap-1 text-sm font-medium"
                aria-expanded={open}
                onClick={() => {
                  toggle(name)
                }}
              >
                <ChevronDownIcon className={open ? 'size-4' : 'size-4 -rotate-90'} aria-hidden />
                {name}
              </button>
            )}
            {open && (
              <div className="divide-y">
                {members.map((field) => (
                  <div key={field.key}>
                    <FieldRow
                      vault={vault}
                      kind={entity.kind}
                      field={field}
                      value={values[field.key]}
                      visibility={overrides[field.key]}
                      editable={editable}
                      save={save}
                      asOf={asOf?.[field.key]}
                      {...(field.temporal
                        ? {
                            history: {
                              open: historyOf === field.key,
                              toggle: () => {
                                setHistoryOf(historyOf === field.key ? null : field.key)
                              },
                            },
                          }
                        : {})}
                    />
                    {historyOf === field.key && (
                      <section
                        aria-label={`${field.label} over time`}
                        className="mb-2 ml-[10.75rem] rounded-md border p-2"
                      >
                        <FactHistory
                          vault={vault}
                          entity={entity}
                          fieldKey={field.key}
                          field={field}
                        />
                      </section>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
