import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { affectedKeys, invalidateAffected } from './invalidate'
import { keys } from './keys'

const NOTHING = { entities: [], dimensions: [], time_changed: false, search_changed: false }

function seeded(): QueryClient {
  const client = new QueryClient()
  for (const key of [
    keys.entity('v', 'e1'),
    keys.entity('v', 'e2'),
    keys.backlinks('v', 'e1'),
    keys.entities('v', { kind: 'event' }),
    keys.tree('v'),
    keys.window('v', 't1', { from: '0', to: '9' }),
    keys.timelines('v', 'd1'),
    keys.timelines('v', 'd2'),
    keys.search('v', { q: 'x' }),
    keys.registry('v'),
    keys.entity('other', 'e1'),
    keys.vaults(),
  ]) {
    client.setQueryData(key, 'cached')
  }
  return client
}

function stale(client: QueryClient): string[] {
  return client
    .getQueryCache()
    .getAll()
    .filter((query) => query.state.isInvalidated)
    .map((query) => JSON.stringify(query.queryKey))
    .sort()
}

describe('invalidateAffected', () => {
  it('maps a write’s affected entities to their queries and the vault’s lists', async () => {
    const client = seeded()
    await invalidateAffected(client, 'v', { ...NOTHING, entities: ['e1'] })
    expect(stale(client)).toEqual(
      [
        keys.entity('v', 'e1'),
        keys.backlinks('v', 'e1'),
        keys.entities('v', { kind: 'event' }),
        keys.tree('v'),
      ]
        .map((key) => JSON.stringify(key))
        .sort(),
    )
  })

  it('refreshes windows on time changes, timelines per dimension, and search', async () => {
    const client = seeded()
    await invalidateAffected(client, 'v', {
      entities: [],
      dimensions: ['d1'],
      time_changed: true,
      search_changed: true,
    })
    const found = stale(client)
    expect(found).toContain(JSON.stringify(keys.window('v', 't1', { from: '0', to: '9' })))
    expect(found).toContain(JSON.stringify(keys.timelines('v', 'd2'))) // time_changed: all timelines
    expect(found).toContain(JSON.stringify(keys.search('v', { q: 'x' })))
    expect(found).not.toContain(JSON.stringify(keys.registry('v')))
    expect(found).not.toContain(JSON.stringify(keys.entity('other', 'e1')))
    expect(found).not.toContain(JSON.stringify(keys.vaults()))
  })

  it('leaves windows and search alone when nothing timed or searchable changed', () => {
    const found = affectedKeys('v', { ...NOTHING, dimensions: ['d1'] }).map((key) => key.join('/'))
    expect(found).toContain('v/timelines/d1')
    expect(found).not.toContain('v/window')
    expect(found).not.toContain('v/search')
  })
})
