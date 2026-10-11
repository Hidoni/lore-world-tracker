import { describe, expect, it } from 'vitest'

import { globalSearchSchema, parseSearch, stringifySearch } from './search'

describe('search params', () => {
  it('keep moments as exact strings', () => {
    const huge = '100000000000000000000000000000001'
    expect(parseSearch(`?at=${huge}&tl=abc&n=7&flag=true`)).toEqual({
      at: huge,
      tl: 'abc',
      n: '7',
      flag: 'true',
    })
  })

  it('round-trip JSON structures and strings that look like them', () => {
    const search = { filters: { kinds: ['event'] }, odd: '[1]', quoted: '"a"', plain: 'x y' }
    expect(parseSearch(stringifySearch(search))).toEqual(search)
    expect(stringifySearch({})).toBe('')
    expect(stringifySearch({ a: undefined, b: '1' })).toBe('?b=1')
  })

  it('validate the global params and drop invalid ones', () => {
    expect(globalSearchSchema.parse({ tl: 't1', at: '42', cal: 'c1' })).toEqual({
      tl: 't1',
      at: '42',
      cal: 'c1',
    })
    expect(globalSearchSchema.parse({ at: 'present' })).toEqual({ at: 'present' })
    expect(globalSearchSchema.parse({ at: 'all' })).toEqual({ at: 'all' })
    expect(globalSearchSchema.parse({ at: '-1', tl: '', cal: 3 })).toEqual({
      at: undefined,
      tl: undefined,
      cal: undefined,
    })
    expect(globalSearchSchema.parse({ at: '007' }).at).toBeUndefined()
  })
})
