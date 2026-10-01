import { describe, expect, it } from 'vitest'

import { cn } from './utils'

describe('cn', () => {
  it('joins clsx-style arguments', () => {
    expect(cn('a', false, null, undefined, ['b', { c: true, d: false }])).toBe('a b c')
  })

  it('resolves Tailwind conflicts in favour of the last class', () => {
    expect(cn('px-2 py-1', 'px-4')).toBe('py-1 px-4')
    expect(cn('bg-primary text-sm', 'bg-destructive/90')).toBe('text-sm bg-destructive/90')
    expect(cn('size-4', 'h-6')).toBe('size-4 h-6')
  })
})
