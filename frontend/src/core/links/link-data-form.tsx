import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

type Data = Record<string, unknown>

interface PropertySchema {
  type?: string | string[]
  enum?: unknown[]
  title?: string
  description?: string
}

interface ObjectSchema {
  type?: string
  properties?: Record<string, PropertySchema>
  required?: string[]
}

/** A JSON value as text (choices and inputs). */
const show = (value: unknown): string => (typeof value === 'string' ? value : JSON.stringify(value))

const SIMPLE = new Set(['string', 'integer', 'number', 'boolean'])
const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

function simpleType(schema: PropertySchema): string | null {
  const types = Array.isArray(schema.type) ? schema.type.filter((t) => t !== 'null') : [schema.type]
  const [type] = types
  return types.length === 1 && type !== undefined && SIMPLE.has(type) ? type : null
}

/** Whether a `data_schema` is an object of simple properties (a form), else JSON is edited. */
export function formFields(schema: unknown): [string, PropertySchema, string][] | null {
  const object = schema as ObjectSchema | null
  if (object?.properties === undefined) return null
  const fields: [string, PropertySchema, string][] = []
  for (const [key, property] of Object.entries(object.properties)) {
    const type = simpleType(property)
    if (type === null && property.enum === undefined) return null
    fields.push([key, property, type ?? 'string'])
  }
  return fields
}

/**
 * The `data` of a link, from its type's `data_schema` (`data-model.md` §6.2): a field per simple
 * property (text, number, checkbox, choice); other schemas edit the JSON. The server validates
 * (`errors[].path = "data.…"`, shown under the field).
 */
export function LinkDataForm({
  schema,
  value,
  onChange,
  errors,
  onInvalidJson,
}: {
  schema: unknown
  value: Data
  onChange: (value: Data) => void
  errors: Record<string, string>
  onInvalidJson: (invalid: boolean) => void
}) {
  const fields = formFields(schema)
  if (fields === null) {
    return (
      <JsonData value={value} onChange={onChange} error={errors.data} onInvalid={onInvalidJson} />
    )
  }
  if (fields.length === 0) return null
  const set = (key: string, next: unknown) => {
    const rest = Object.fromEntries(Object.entries(value).filter(([name]) => name !== key))
    onChange(next === undefined ? rest : { ...rest, [key]: next })
  }
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-sm font-medium">Details</legend>
      {fields.map(([key, property, type]) => {
        const id = `link-data-${key}`
        const label = property.title ?? key
        const error = errors[`data.${key}`]
        const current = value[key]
        if (type === 'boolean') {
          return (
            <div key={key} className="flex items-center gap-2">
              <Checkbox
                id={id}
                checked={current === true}
                onCheckedChange={(checked) => {
                  set(key, checked === true ? true : undefined)
                }}
              />
              <Label htmlFor={id}>{label}</Label>
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
          )
        }
        return (
          <div key={key} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{label}</Label>
            {property.enum ? (
              <select
                id={id}
                className={SELECT_CLASS}
                value={current === undefined ? '' : show(current)}
                onChange={(event) => {
                  const choice = property.enum?.find(
                    (option) => show(option) === event.target.value,
                  )
                  set(key, event.target.value === '' ? undefined : choice)
                }}
              >
                <option value="">—</option>
                {property.enum.map((option) => (
                  <option key={show(option)} value={show(option)}>
                    {show(option)}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id={id}
                inputMode={type === 'string' ? undefined : 'decimal'}
                aria-invalid={error ? true : undefined}
                value={current === undefined ? '' : show(current)}
                onChange={(event) => {
                  const text = event.target.value
                  if (text === '') set(key, undefined)
                  else if (type === 'string') set(key, text)
                  // Numbers stay text until they parse, so typing "1." works.
                  else set(key, /^-?\d+(\.\d+)?$/.test(text) ? Number(text) : text)
                }}
              />
            )}
            {property.description && (
              <p className="text-xs text-muted-foreground">{property.description}</p>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        )
      })}
    </fieldset>
  )
}

function JsonData({
  value,
  onChange,
  error,
  onInvalid,
}: {
  value: Data
  onChange: (value: Data) => void
  error: string | undefined
  onInvalid: (invalid: boolean) => void
}) {
  const text = Object.keys(value).length === 0 ? '' : JSON.stringify(value, null, 2)
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="link-data-json">Details (JSON)</Label>
      <Textarea
        id="link-data-json"
        className="font-mono text-xs"
        defaultValue={text}
        aria-invalid={error ? true : undefined}
        onChange={(event) => {
          const raw = event.target.value.trim()
          if (raw === '') {
            onInvalid(false)
            onChange({})
            return
          }
          try {
            const parsed: unknown = JSON.parse(raw)
            const ok = typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
            onInvalid(!ok)
            if (ok) onChange(parsed as Data)
          } catch {
            onInvalid(true)
          }
        }}
      />
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
