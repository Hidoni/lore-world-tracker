import { describe, expect, it } from 'vitest'

import { ENGINE_VERSION } from './index'

describe('@lore/chronology', () => {
  it('exports a semver engine version', () => {
    expect(ENGINE_VERSION).toMatch(/^\d+\.\d+\.\d+$/)
  })
})
