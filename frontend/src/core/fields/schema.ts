import { z } from 'zod'

import type { components } from '@/data'

export type FieldDef = components['schemas']['FieldOut']

/** Mirrors `lore.core.fields.values` (data-model.md §4.2): the client checks before saving. */
const MAX_DIGITS = 1000
const INTEGER = /^(0|-?[1-9][0-9]*)$/
const DECIMAL = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/
const NEGATIVE_ZERO = /^-0(\.0+)?$/
const COLOR = /^#[0-9a-fA-F]{6}$/
const MAX_URL_LENGTH = 2048
const MAX_UNIT_LENGTH = 100

const integer = z
  .string()
  .regex(INTEGER, 'Must be a whole number, like 42 or -7')
  .refine((text) => text.replace('-', '').length <= MAX_DIGITS, `At most ${MAX_DIGITS} digits`)

const decimal = z
  .string()
  .regex(DECIMAL, 'Must be a decimal number, like 1.75')
  .refine((text) => !NEGATIVE_ZERO.test(text), 'Must be a decimal number, like 1.75')
  .refine(
    (text) => text.replace(/[^0-9]/g, '').length <= MAX_DIGITS,
    `At most ${MAX_DIGITS} digits`,
  )

const url = z
  .string()
  .max(MAX_URL_LENGTH, `At most ${MAX_URL_LENGTH} characters`)
  .refine((text) => !/\s/.test(text), 'Must not contain spaces')
  .refine((text) => {
    try {
      const parsed = new URL(text)
      return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname !== ''
    } catch {
      return false
    }
  }, 'Must be an http(s) URL')

const jsonObject = z.record(z.string(), z.unknown())

/** The schema of one value of a field type (`null` for unknown types: any JSON). */
function valueSchema(field: FieldDef): z.ZodType {
  const keys = field.options.map((option) => option.key)
  switch (field.type) {
    case 'text':
      return z.string().refine((text) => !/[\r\n]/.test(text), 'Must be a single line')
    case 'long_text':
      return z.string()
    case 'rich_text':
      return jsonObject
    case 'integer':
      return integer
    case 'decimal':
      return decimal
    case 'boolean':
      return z.boolean()
    case 'enum':
      return z.string().refine((key) => keys.includes(key), `Must be one of ${keys.join(', ')}`)
    case 'multi_enum':
      return z
        .array(z.string().refine((key) => keys.includes(key), `Must be one of ${keys.join(', ')}`))
        .refine((list) => new Set(list).size === list.length, 'Must not repeat an option')
    case 'url':
      return url
    case 'color':
      return z
        .string()
        .regex(COLOR, 'Must be a color like #a0b1c2')
        .transform((color) => color.toLowerCase())
    case 'measurement':
      return z.object({
        value: decimal,
        unit: z
          .string()
          .trim()
          .min(1, 'A unit is required')
          .max(MAX_UNIT_LENGTH, `At most ${MAX_UNIT_LENGTH} characters`),
      })
    case 'duration':
    case 'time_point':
      return jsonObject // validated structurally by the server until M5
    default:
      return z.unknown()
  }
}

/** Whether a value counts as empty (`required` fields can't be: data-model.md §4.3). */
export function isEmpty(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/**
 * The schema of a field's value: its type's (a list of them when `multiple`), `null` allowed to
 * clear it unless the field is `required`.
 */
export function fieldSchema(field: FieldDef): z.ZodType {
  const one = valueSchema(field)
  const value = field.multiple && field.type !== 'multi_enum' ? z.array(one) : one
  if (field.required) {
    return z
      .unknown()
      .superRefine((input, context) => {
        if (isEmpty(input)) {
          context.addIssue({ code: 'custom', message: 'Required' })
          return
        }
        const parsed = value.safeParse(input)
        if (!parsed.success) for (const issue of parsed.error.issues) context.addIssue({ ...issue })
      })
      .transform((input) => {
        const parsed = value.safeParse(input)
        return parsed.success ? parsed.data : input
      })
  }
  return z.union([z.null(), value])
}

/** The schema of a kind's field values (create forms): one member per field, live fields only. */
export function fieldsSchema(fields: readonly FieldDef[]) {
  return z.object(
    Object.fromEntries(
      fields
        .filter((field) => !field.archived)
        .map((field) => [
          field.key,
          field.required ? fieldSchema(field) : fieldSchema(field).optional(),
        ]),
    ),
  )
}

/** The first error message for a value, or `null` when it's valid. */
export function validateField(field: FieldDef, value: unknown): string | null {
  const parsed = fieldSchema(field).safeParse(value)
  return parsed.success ? null : (parsed.error.issues[0]?.message ?? 'Invalid value')
}

/** The value to store: normalized like the server would (lowercase colors, trimmed units). */
export function normalizeField(field: FieldDef, value: unknown): unknown {
  const parsed = fieldSchema(field).safeParse(value)
  return parsed.success ? parsed.data : value
}
