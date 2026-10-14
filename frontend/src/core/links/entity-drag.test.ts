import { describe, expect, it } from 'vitest'

import { carriesEntity, droppedEntity, ENTITY_MIME, setEntityDrag } from './entity-drag'

function transfer(data: Record<string, string> = {}) {
  const stored = { ...data }
  return {
    get types() {
      return Object.keys(stored)
    },
    getData: (type: string) => stored[type] ?? '',
    setData: (type: string, value: string) => {
      stored[type] = value
    },
    effectAllowed: 'all',
  } as unknown as DataTransfer
}

describe('dragged entities', () => {
  it('carry their own data, or an entity page URL of the vault', () => {
    const own = transfer()
    setEntityDrag(own, { id: 'a1', name: 'Crown', kind: 'artifact' })
    expect(carriesEntity(own)).toBe(true)
    expect(droppedEntity(own, 'v1')).toEqual({ id: 'a1', name: 'Crown', kind: 'artifact' })

    const link = transfer({ 'text/uri-list': '# comment\nhttp://localhost/v/v1/e/a%201?tab=x' })
    expect(carriesEntity(link)).toBe(true)
    expect(droppedEntity(link, 'v1')).toEqual({ id: 'a 1' })
    expect(droppedEntity(link, 'v2')).toBeNull() // another vault's entity
    expect(droppedEntity(transfer({ 'text/plain': 'just text' }), 'v1')).toBeNull()
    expect(carriesEntity(transfer({ 'text/plain': 'x' }))).toBe(false)
    expect(droppedEntity(transfer({ [ENTITY_MIME]: 'not json' }), 'v1')).toBeNull()
  })
})
