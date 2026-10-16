import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Textarea } from '@/components/ui/textarea'
import { SELECT_CLASS } from '@/components/settings-section'
import {
  fieldErrors,
  useCreateCustomField,
  useFieldValues,
  useRegistry,
  useUpdateCustomField,
  type CustomField,
} from '@/data'

import { problemText, SLUG, slugify, VISIBILITIES } from './shared'

interface Option {
  key: string
  label: string
}
type Visibility = (typeof VISIBILITIES)[number]['value']

const CHOICE_TYPES = new Set(['enum', 'multi_enum'])
/** The safe type conversions (custom_fields.md, Rules for changes): values follow. */
export const CONVERSIONS: Record<string, readonly string[]> = {
  text: ['long_text', 'enum'],
  long_text: ['text'],
  enum: ['multi_enum'],
  integer: ['decimal'],
}

/**
 * Creates or edits a custom field of `kind` (`'*'`: every kind). Editing offers the safe type
 * conversions only; text → enum asks which option each existing value becomes, and turning
 * `temporal` off asks what happens to the field's facts.
 */
export function FieldDialog({
  vault,
  kind,
  field,
  onClose,
}: {
  vault: string
  kind: string
  field: CustomField | null
  onClose: () => void
}) {
  const registry = useRegistry(vault)
  const create = useCreateCustomField(vault)
  const update = useUpdateCustomField(vault)
  const mutation = field ? update : create
  const [label, setLabel] = useState(field?.label ?? '')
  const [slug, setSlug] = useState<string | null>(null)
  const [type, setType] = useState(field?.type ?? 'text')
  const [options, setOptions] = useState<Option[]>(
    field?.options.map(({ key, label }) => ({ key, label })) ?? [],
  )
  const [multiple, setMultiple] = useState(field?.multiple ?? false)
  const [required, setRequired] = useState(field?.required ?? false)
  const [temporal, setTemporal] = useState(field?.temporal ?? false)
  const [facts, setFacts] = useState<'keep' | 'drop'>('keep')
  const [visibility, setVisibility] = useState<Visibility>(field?.default_visibility ?? 'public')
  const [section, setSection] = useState(field?.section ?? '')
  const [help, setHelp] = useState(field?.help ?? '')
  const [searchable, setSearchable] = useState(field?.searchable ?? true)
  const [valueMap, setValueMap] = useState<Record<string, string>>({})
  const key = slug ?? slugify(label)
  const badKey = field === null && !SLUG.test(key)
  const types = (registry.data?.field_types ?? []).filter(
    (option) =>
      field === null ||
      option.key === field.type ||
      (CONVERSIONS[field.type] ?? []).includes(option.key),
  )
  const mapping = field?.type === 'text' && type === 'enum'
  const values = useFieldValues(
    vault,
    { kind: kind === '*' ? 'misc' : kind, field: field?.key ?? '', limit: 200 },
    { enabled: mapping && kind !== '*' },
  )
  const existing = mapping ? (values.data?.items ?? []) : []
  const unmapped = existing.filter((item) => !(item.value in valueMap)).length
  const choice = CHOICE_TYPES.has(type)
  const badOptions =
    choice &&
    (options.length === 0 ||
      options.some((option) => !SLUG.test(option.key) || option.label.trim() === '') ||
      new Set(options.map((option) => option.key)).size !== options.length)
  const turningOff = field?.temporal === true && !temporal
  const errors = fieldErrors(mutation.error)
  const failure = mutation.error ? problemText(mutation.error) : null

  const submit = () => {
    const common = {
      label: label.trim(),
      options: choice ? options.map(({ key, label }) => ({ key, label: label.trim() })) : [],
      multiple: type === 'multi_enum' ? false : multiple,
      required,
      temporal,
      default_visibility: visibility,
      section: section.trim() || null,
      help: help.trim(),
      searchable,
    }
    const done = {
      onSuccess: () => {
        toast.success(field ? `Saved ${common.label}` : `Created ${common.label}`)
        onClose()
      },
    }
    if (field) {
      const body = {
        ...common,
        revision: field.revision,
        ...(type !== field.type ? { type } : {}),
        ...(mapping
          ? {
              value_map: Object.fromEntries(
                Object.entries(valueMap).map(([from, to]) => [from, to === '' ? null : to]),
              ),
            }
          : {}),
        ...(turningOff ? { facts } : {}),
      }
      update.mutate({ id: field.id, body }, done)
    } else {
      create.mutate({ ...common, kind_key: kind, key, type }, done)
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto">
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{field ? `Edit ${field.label}` : 'New field'}</DialogTitle>
            <DialogDescription>
              {field ? field.key : `Its values are stored as custom.${key || '…'}.`}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="field-label">Label</Label>
            <Input
              id="field-label"
              placeholder="Power"
              value={label}
              maxLength={100}
              onChange={(event) => {
                setLabel(event.target.value)
              }}
            />
            {errors.label && <p className="text-sm text-destructive">{errors.label}</p>}
          </div>
          {field === null && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="field-key">Key</Label>
              <Input
                id="field-key"
                value={key}
                maxLength={60}
                onChange={(event) => {
                  setSlug(event.target.value)
                }}
              />
              {(errors.key ?? badKey) && (
                <p className="text-sm text-destructive">
                  {errors.key ?? 'Lowercase letters, digits and _, starting with a letter.'}
                </p>
              )}
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="field-type">Type</Label>
            <select
              id="field-type"
              className={SELECT_CLASS}
              value={type}
              onChange={(event) => {
                const next = event.target.value
                setType(next)
                if (field?.type === 'enum' && next === 'multi_enum') setMultiple(false)
              }}
            >
              {types.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
            {field && (
              <p className="text-xs text-muted-foreground">
                Only safe conversions are offered; values follow in the same undoable change.
              </p>
            )}
            {errors.type && <p className="text-sm text-destructive">{errors.type}</p>}
          </div>
          {choice && <OptionsEditor options={options} onChange={setOptions} />}
          {mapping && (
            <ValueMapping
              values={existing.map((item) => item.value)}
              options={options}
              mapping={valueMap}
              onChange={setValueMap}
              partial={kind === '*'}
            />
          )}
          <div className="flex flex-col gap-2 text-sm">
            {type !== 'multi_enum' && (
              <Toggle id="field-multiple" checked={multiple} onChange={setMultiple}>
                Several values
              </Toggle>
            )}
            <Toggle id="field-required" checked={required} onChange={setRequired}>
              Required
            </Toggle>
            <Toggle id="field-temporal" checked={temporal} onChange={setTemporal}>
              Changes over time (a history of values)
            </Toggle>
            {turningOff && (
              <fieldset className="flex flex-col gap-1 pl-6">
                <legend className="text-sm">Its facts (dated values)</legend>
                {(['keep', 'drop'] as const).map((value) => (
                  <label key={value} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="field-facts"
                      checked={facts === value}
                      onChange={() => {
                        setFacts(value)
                      }}
                    />
                    {value === 'keep' ? 'Keep them (hidden)' : 'Move them to the trash'}
                  </label>
                ))}
              </fieldset>
            )}
            <Toggle id="field-searchable" checked={searchable} onChange={setSearchable}>
              Searchable
            </Toggle>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="field-visibility">Default visibility</Label>
              <select
                id="field-visibility"
                className={SELECT_CLASS}
                value={visibility}
                onChange={(event) => {
                  setVisibility(event.target.value as Visibility)
                }}
              >
                {VISIBILITIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="field-section">Section</Label>
              <Input
                id="field-section"
                placeholder="General"
                value={section}
                maxLength={100}
                onChange={(event) => {
                  setSection(event.target.value)
                }}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="field-help">Help text</Label>
            <Textarea
              id="field-help"
              value={help}
              onChange={(event) => {
                setHelp(event.target.value)
              }}
            />
          </div>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                mutation.isPending ||
                label.trim() === '' ||
                badKey ||
                badOptions ||
                (mapping && unmapped > 0)
              }
            >
              {field ? 'Save' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Toggle({
  id,
  checked,
  onChange,
  children,
}: {
  id: string
  checked: boolean
  onChange: (checked: boolean) => void
  children: string
}) {
  return (
    <div className="flex items-center gap-2">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(value) => {
          onChange(value === true)
        }}
      />
      <Label htmlFor={id}>{children}</Label>
    </div>
  )
}

/** The options of a choice field: label and key per row, added, removed and reordered. */
function OptionsEditor({
  options,
  onChange,
}: {
  options: Option[]
  onChange: (options: Option[]) => void
}) {
  const set = (index: number, option: Option) => {
    onChange(options.map((other, at) => (at === index ? option : other)))
  }
  const move = (index: number, by: number) => {
    const next = [...options]
    const [moved] = next.splice(index, 1)
    if (moved) next.splice(index + by, 0, moved)
    onChange(next)
  }
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium">Options</legend>
      <ul aria-label="Options" className="flex flex-col gap-1">
        {options.map((option, index) => (
          <li key={index} className="flex items-center gap-1">
            <Input
              aria-label={`Option ${index + 1} label`}
              value={option.label}
              maxLength={100}
              onChange={(event) => {
                const label = event.target.value
                const followed = option.key === '' || option.key === slugify(option.label)
                set(index, { label, key: followed ? slugify(label) : option.key })
              }}
            />
            <Input
              aria-label={`Option ${index + 1} key`}
              className="w-32 font-mono text-xs"
              value={option.key}
              maxLength={60}
              onChange={(event) => {
                set(index, { ...option, key: event.target.value })
              }}
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Move option ${index + 1} up`}
              disabled={index === 0}
              onClick={() => {
                move(index, -1)
              }}
            >
              ↑
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`Remove option ${index + 1}`}
              onClick={() => {
                onChange(options.filter((_, at) => at !== index))
              }}
            >
              ✕
            </Button>
          </li>
        ))}
      </ul>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="self-start"
        onClick={() => {
          onChange([...options, { key: '', label: '' }])
        }}
      >
        Add option
      </Button>
    </fieldset>
  )
}

/** text → enum: which option each existing value becomes (or none: the value is cleared). */
function ValueMapping({
  values,
  options,
  mapping,
  onChange,
  partial,
}: {
  values: string[]
  options: Option[]
  mapping: Record<string, string>
  onChange: (mapping: Record<string, string>) => void
  partial: boolean
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium">Existing values become</legend>
      {partial && (
        <p className="text-xs text-muted-foreground">
          The field is on every kind: values the list misses are reported when you save.
        </p>
      )}
      {values.length === 0 && !partial && (
        <p className="text-xs text-muted-foreground">No entity has a value yet.</p>
      )}
      <ul className="flex flex-col gap-1">
        {values.map((value) => (
          <li key={value} className="grid grid-cols-2 items-center gap-2 text-sm">
            <span className="truncate">{value}</span>
            <select
              aria-label={`Option for ${value}`}
              className={SELECT_CLASS}
              value={mapping[value] ?? '?'}
              onChange={(event) => {
                onChange({ ...mapping, [value]: event.target.value })
              }}
            >
              <option value="?" disabled>
                Choose…
              </option>
              {options.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label || option.key}
                </option>
              ))}
              <option value="">(clear the value)</option>
            </select>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}
