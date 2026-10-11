import { afterEach, describe, expect, it, vi } from 'vitest'

import { readStored, writeStored } from './storage'

describe('storage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('reads, writes and removes values', () => {
    writeStored('k', 'v')
    expect(readStored('k')).toBe('v')
    writeStored('k', null)
    expect(readStored('k')).toBeNull()
  })

  it('never throws when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readStored('k')).toBeNull()
    expect(() => {
      writeStored('k', 'v')
    }).not.toThrow()
  })
})
