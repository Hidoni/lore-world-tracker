import { describe, expect, it } from 'vitest'

import { linkType } from '@/test/fake-vault'

import { formFields } from './link-data-form'
import { linkOptions, type LinkTypeOut } from './link-options'

const TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('t.member_of', 'member of', {
    inverse_label: 'has member',
    source_kinds: ['character'],
    target_kinds: ['group'],
  }),
  linkType('t.allied', 'allied with', {
    symmetric: true,
    source_kinds: ['group'],
    target_kinds: ['group'],
  }),
  linkType('t.mentor', 'mentor of', { source_kinds: ['character'], target_kinds: ['character'] }),
  linkType('t.gone', 'gone', { archived: true }),
] as LinkTypeOut[]

const ids = (here: string, there: string | null) =>
  linkOptions(TYPES, here, there).map((option) => option.id)

describe('linkOptions', () => {
  it('offers types whose kinds fit, forward and reversed, never archived ones', () => {
    expect(ids('character', 'group')).toEqual(['t.member_of', 'core.related'])
    expect(ids('group', 'character')).toEqual(['t.member_of:reverse', 'core.related'])
    expect(ids('group', 'group')).toEqual(['t.allied', 'core.related'])
    // A type between the same kinds is offered both ways (mentor of / mentored by).
    expect(ids('character', 'character')).toEqual(['t.mentor', 't.mentor:reverse', 'core.related'])
    expect(ids('character', null)).toEqual([
      't.member_of',
      't.mentor',
      't.mentor:reverse',
      'core.related',
    ])
  })

  it('labels reversed options with the inverse label', () => {
    const [reversed] = linkOptions(TYPES, 'group', 'character')
    expect(reversed).toMatchObject({ label: 'has member', reversed: true })
    const mentor = linkOptions(TYPES, 'character', 'character').find((option) => option.reversed)
    expect(mentor?.label).toBe('mentor of (reverse)')
  })
})

describe('formFields', () => {
  it('builds a form from simple object schemas, else falls back to JSON', () => {
    expect(
      formFields({
        type: 'object',
        properties: {
          rank: { type: 'string' },
          years: { type: ['integer', 'null'] },
          oath: { enum: ['blood', 'word'] },
        },
      })?.map(([key, , type]) => [key, type]),
    ).toEqual([
      ['rank', 'string'],
      ['years', 'integer'],
      ['oath', 'string'],
    ])
    expect(formFields({ type: 'object', properties: { tags: { type: 'array' } } })).toBeNull()
    expect(formFields({ type: 'array' })).toBeNull()
  })
})
