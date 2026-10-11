import type { ComponentProps, KeyboardEvent, ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { RichTextView, isDoc } from '@/editor'

import { docToText, textToDoc } from './rich-text-fallback'
import type { FieldDef } from './schema'

export interface FieldEditorProps {
  field: FieldDef
  id: string
  value: unknown
  /** The draft changed (text inputs: saved on Enter or blur). */
  onChange: (value: unknown) => void
  /** Save now (with `value`, or the current draft). */
  onCommit: (value?: unknown) => void
  onCancel: () => void
  invalid: boolean
  disabled?: boolean
}

/** Types implemented in M5 (time pickers) and by the media module. */
export const PLACEHOLDER_TYPES = new Set(['duration', 'time_point'])

const SELECT_CLASS =
  'h-9 w-full rounded-md border bg-transparent px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** Empty text clears the field (`null`). */
function orNull(value: string): string | null {
  return value === '' ? null : value
}

function keys(onCommit: () => void, onCancel: () => void, multiline = false) {
  return (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
    } else if (event.key === 'Enter' && (!multiline || event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      onCommit()
    }
  }
}

/** The editor of one field value, per field type (data-model.md §4.2). */
export function FieldEditor(props: FieldEditorProps): ReactNode {
  const { field, id, value, onChange, onCommit, onCancel, invalid, disabled } = props
  const common = {
    id,
    disabled,
    'aria-invalid': invalid,
    onBlur: () => {
      onCommit()
    },
  }
  const single: ComponentProps<'input'> = {
    ...common,
    value: text(value),
    onChange: (event) => {
      onChange(orNull(event.target.value))
    },
    onKeyDown: keys(() => {
      onCommit()
    }, onCancel),
  }
  switch (field.type) {
    case 'text':
      return <Input {...single} />
    case 'url':
      return <Input {...single} type="url" placeholder="https://" />
    case 'integer':
      return <Input {...single} inputMode="numeric" placeholder="0" />
    case 'decimal':
      return <Input {...single} inputMode="decimal" placeholder="0.0" />
    case 'long_text':
      return (
        <Textarea
          {...common}
          value={text(value)}
          onChange={(event) => {
            onChange(orNull(event.target.value))
          }}
          onKeyDown={keys(
            () => {
              onCommit()
            },
            onCancel,
            true,
          )}
        />
      )
    case 'rich_text':
      // The create dialog's plain fallback (the fields panel edits rich text in the editor).
      return (
        <Textarea
          {...common}
          value={docToText(value)}
          onChange={(event) => {
            onChange(event.target.value === '' ? null : textToDoc(event.target.value))
          }}
          onKeyDown={keys(
            () => {
              onCommit()
            },
            onCancel,
            true,
          )}
        />
      )
    case 'boolean':
      return (
        <input
          id={id}
          type="checkbox"
          className="size-4"
          disabled={disabled}
          checked={value === true}
          onChange={(event) => {
            onCommit(event.target.checked)
          }}
        />
      )
    case 'enum':
      return (
        <select
          id={id}
          className={SELECT_CLASS}
          disabled={disabled}
          aria-invalid={invalid}
          value={text(value)}
          onChange={(event) => {
            onCommit(orNull(event.target.value))
          }}
          onKeyDown={keys(() => {
            onCommit()
          }, onCancel)}
        >
          {!field.required && <option value="">—</option>}
          {field.options.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      )
    case 'multi_enum': {
      const selected = Array.isArray(value) ? (value as string[]) : []
      return (
        <fieldset id={id} className="flex flex-wrap gap-3" disabled={disabled}>
          {field.options.map((option) => (
            <label key={option.key} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(option.key)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? field.options
                        .map((o) => o.key)
                        .filter((k) => k === option.key || selected.includes(k))
                    : selected.filter((k) => k !== option.key)
                  onCommit(next.length === 0 ? null : next)
                }}
              />
              {option.label}
            </label>
          ))}
        </fieldset>
      )
    }
    case 'color':
      return (
        <div className="flex items-center gap-2">
          <input
            type="color"
            aria-label={`${field.label} picker`}
            disabled={disabled}
            value={/^#[0-9a-fA-F]{6}$/.test(text(value)) ? text(value) : '#000000'}
            onChange={(event) => {
              onCommit(event.target.value)
            }}
          />
          <Input {...single} placeholder="#rrggbb" className="w-32" />
        </div>
      )
    case 'measurement': {
      const current = (value ?? { value: '', unit: '' }) as { value: string; unit: string }
      const set = (patch: Partial<typeof current>) => {
        const next = { ...current, ...patch }
        onChange(next.value === '' && next.unit === '' ? null : next)
      }
      return (
        <div
          className="flex items-center gap-2"
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) onCommit()
          }}
        >
          <Input
            id={id}
            aria-invalid={invalid}
            disabled={disabled}
            inputMode="decimal"
            placeholder="0.0"
            className="w-32"
            value={current.value}
            onChange={(event) => {
              set({ value: event.target.value })
            }}
            onKeyDown={keys(() => {
              onCommit()
            }, onCancel)}
          />
          <Input
            aria-label={`${field.label} unit`}
            aria-invalid={invalid}
            disabled={disabled}
            placeholder="unit"
            className="w-28"
            value={current.unit}
            onChange={(event) => {
              set({ unit: event.target.value })
            }}
            onKeyDown={keys(() => {
              onCommit()
            }, onCancel)}
          />
        </div>
      )
    }
    default:
      return (
        <p className="text-sm text-muted-foreground">
          {PLACEHOLDER_TYPES.has(field.type)
            ? 'Editing arrives with the time pickers (M5).'
            : 'This field type has no editor.'}
        </p>
      )
  }
}

/** A field value for reading. */
export function FieldDisplay({
  vault,
  field,
  value,
}: {
  vault: string
  field: FieldDef
  value: unknown
}): ReactNode {
  if (
    value === null ||
    value === undefined ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  ) {
    return <span className="text-muted-foreground">—</span>
  }
  const label = (key: unknown) =>
    field.options.find((option) => option.key === key)?.label ?? String(key)
  if (field.multiple && field.type !== 'multi_enum' && Array.isArray(value)) {
    return (
      <ul className="flex flex-col">
        {(value as unknown[]).map((item, index) => (
          <li key={index}>
            <FieldDisplay vault={vault} field={{ ...field, multiple: false }} value={item} />
          </li>
        ))}
      </ul>
    )
  }
  switch (field.type) {
    case 'boolean':
      return <span>{value === true ? 'Yes' : 'No'}</span>
    case 'enum':
      return <Badge variant="secondary">{label(value)}</Badge>
    case 'multi_enum':
      return (
        <span className="flex flex-wrap gap-1">
          {(value as string[]).map((key) => (
            <Badge key={key} variant="secondary">
              {label(key)}
            </Badge>
          ))}
        </span>
      )
    case 'url':
      return (
        <a
          href={text(value)}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="text-primary underline"
        >
          {text(value)}
        </a>
      )
    case 'color':
      return (
        <span className="flex items-center gap-2">
          <span
            className="inline-block size-4 rounded border"
            style={{ backgroundColor: text(value) }}
            aria-hidden
          />
          {text(value)}
        </span>
      )
    case 'measurement': {
      const measured = value as { value: string; unit: string }
      return (
        <span>
          {measured.value} {measured.unit}
        </span>
      )
    }
    case 'long_text':
      return <span className="whitespace-pre-wrap">{text(value)}</span>
    case 'rich_text':
      return isDoc(value) && (value.content ?? []).length > 0 ? (
        <div className="w-full">
          <RichTextView vault={vault} doc={value} />
        </div>
      ) : (
        <span className="text-muted-foreground">—</span>
      )
    case 'text':
    case 'integer':
    case 'decimal':
      return <span>{text(value)}</span>
    default:
      return <code className="text-xs">{JSON.stringify(value)}</code>
  }
}
