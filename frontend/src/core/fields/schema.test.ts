import { describe, expect, it } from 'vitest'

import { docToText, textToDoc } from './rich-text-fallback'
import { fieldsSchema, isEmpty, normalizeField, validateField, type FieldDef } from './schema'

function field(type: string, extra: Partial<FieldDef> = {}): FieldDef {
  return {
    key: type,
    label: type,
    type,
    options: [
      { key: 'red', label: 'Red', color: null },
      { key: 'blue', label: 'Blue', color: null },
    ],
    multiple: false,
    required: false,
    temporal: false,
    default_visibility: 'public',
    section: null,
    sort: 0,
    help: '',
    searchable: true,
    archived: false,
    ...extra,
  }
}

const HUGE = '123456789012345678901234567890123456789'

describe('field schemas (data-model.md §4.2)', () => {
  it.each([
    ['text', 'one line', 'two\nlines'],
    ['long_text', 'two\nlines', 42],
    ['rich_text', { type: 'doc', content: [] }, 'plain'],
    ['integer', HUGE, '1.5'],
    ['integer', `-${HUGE}`, '007'],
    ['decimal', '1.50', '-0'],
    ['decimal', '-3', '1e5'],
    ['boolean', true, 'yes'],
    ['enum', 'red', 'green'],
    ['multi_enum', ['red', 'blue'], ['red', 'red']],
    ['url', 'https://example.org/a', 'ftp://example.org'],
    ['url', 'http://x.y', 'https://exa mple.org'],
    ['color', '#A0b1C2', 'red'],
    ['measurement', { value: '1.5', unit: ' m ' }, { value: '1.5', unit: '' }],
    ['measurement', { value: '2', unit: 'kg' }, { value: '1,5', unit: 'kg' }],
    ['time_point', { anchor: { kind: 'absolute', t: '0' }, precision: 'base' }, 'now'],
  ])('%s accepts %j and rejects %j', (type, valid, invalid) => {
    const def = field(type)
    expect(validateField(def, valid)).toBeNull()
    expect(validateField(def, invalid)).not.toBeNull()
    expect(validateField(def, null)).toBeNull() // optional fields can be cleared
  })

  it('normalizes like the server: lowercase colors, trimmed units, exact decimals', () => {
    expect(normalizeField(field('color'), '#A0B1C2')).toBe('#a0b1c2')
    expect(normalizeField(field('measurement'), { value: '1.50', unit: ' m ' })).toEqual({
      value: '1.50',
      unit: 'm',
    })
    expect(normalizeField(field('integer'), HUGE)).toBe(HUGE) // a string, never a number
  })

  it('requires a non-empty value for required fields', () => {
    const def = field('text', { required: true })
    expect(validateField(def, null)).toBe('Required')
    expect(validateField(def, '')).toBe('Required')
    expect(validateField(field('multi_enum', { required: true }), [])).toBe('Required')
    expect(validateField(def, 'x')).toBeNull()
    expect(isEmpty([])).toBe(true)
    expect(isEmpty(false)).toBe(false)
  })

  it('takes lists of values for multiple fields', () => {
    const def = field('integer', { multiple: true })
    expect(validateField(def, ['1', '2'])).toBeNull()
    expect(validateField(def, ['1', 'x'])).not.toBeNull()
  })

  it('builds a form schema for a kind (live fields only)', () => {
    const schema = fieldsSchema([
      field('text', { key: 'title', required: true }),
      field('integer', { key: 'age' }),
      field('text', { key: 'old', archived: true }),
    ])
    expect(schema.safeParse({ title: 'x', age: '3' }).success).toBe(true)
    expect(schema.safeParse({ age: '3' }).success).toBe(false)
    expect(Object.keys(schema.shape)).toEqual(['title', 'age'])
  })

  it('keeps rich text as a document until the editor lands', () => {
    const doc = textToDoc('first\n\nthird')
    expect(docToText(doc)).toBe('first\n\nthird')
    expect(docToText(null)).toBe('')
  })
})
