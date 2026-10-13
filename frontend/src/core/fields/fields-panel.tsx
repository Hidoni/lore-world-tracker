import { ChevronDownIcon, PencilIcon } from 'lucide-react'
import { Suspense, useId, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useExtensionRecord } from '@/core/modules'
import { fieldErrors, isRevisionConflict, type components, type Entity } from '@/data'
import { LazyRichTextEditor, isDoc, type SaveOutcome } from '@/editor'
import { readStored, writeStored } from '@/lib/storage'

import { FieldDisplay, FieldEditor, PLACEHOLDER_TYPES } from './editors'
import { normalizeField, validateField, type FieldDef } from './schema'

type Visibility = components['schemas']['Visibility']
interface Change {
  fields?: Record<string, unknown>
  field_visibility?: Record<string, Visibility | null>
}
type Saver = (change: Change) => Promise<{ ok: true } | { ok: false; error: unknown }>

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

function FieldRow({
  vault,
  kind,
  field,
  value,
  visibility,
  editable,
  save,
}: {
  vault: string
  kind: string
  field: FieldDef
  value: unknown
  visibility: Visibility | undefined
  editable: boolean
  save: Saver
}) {
  const id = useId()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const renderers = useExtensionRecord('fieldTypeRenderers', vault)
  const Renderer = renderers[field.type]
  // Core types have editors; time types arrive with M5 and module types bring their own (media).
  const canEditType =
    editable && Object.hasOwn(EDITABLE, field.type) && !PLACEHOLDER_TYPES.has(field.type)
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
        ) : (
          <div className="flex min-h-9 items-center text-sm">
            {Renderer !== undefined ? (
              <Renderer vault={vault} fieldKey={field.key} value={value} />
            ) : (
              <FieldDisplay vault={vault} field={field} value={value} />
            )}
          </div>
        )}
        {error !== null && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {field.help && <p className="text-xs text-muted-foreground">{field.help}</p>}
      </div>
      <div className="flex items-center gap-1">
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
 * the field definitions before saving; the per-field visibility select sets an override.
 */
export function FieldsPanel({
  vault,
  entity,
  fields,
  editable,
  save,
}: {
  vault: string
  entity: Entity
  fields: readonly FieldDef[]
  editable: boolean
  save: Saver
}) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(entity.kind))
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
                  <FieldRow
                    key={field.key}
                    vault={vault}
                    kind={entity.kind}
                    field={field}
                    value={values[field.key]}
                    visibility={overrides[field.key]}
                    editable={editable}
                    save={save}
                  />
                ))}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
