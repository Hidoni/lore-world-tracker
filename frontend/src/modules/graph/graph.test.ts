import { beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_FILTERS,
  graphQuery,
  readPositions,
  readViews,
  writePositions,
  writeViews,
} from './filters'
import { CATEGORY_COLORS, edgeCategory, edgeStyle, mergeStyles, nodeColor } from './styles'

beforeEach(() => {
  localStorage.clear()
})

describe('graph filters', () => {
  it('turn into the request', () => {
    expect(graphQuery(DEFAULT_FILTERS, 'd1', undefined)).toEqual({ dimension: 'd1' })
    expect(
      graphQuery(
        {
          ...DEFAULT_FILTERS,
          scope: 'all',
          kinds: ['character'],
          linkTypes: ['characters.spouse_of'],
          tags: ['t1'],
          mentions: false,
          hierarchy: false,
          center: 'c1',
          depth: 3,
        },
        'd1',
        { timeline: 'tl', at: '42' },
      ),
    ).toEqual({
      center: 'c1',
      depth: 3,
      kind: ['character'],
      link_type: ['characters.spouse_of'],
      tag: ['t1'],
      include_mentions: false,
      include_hierarchy: false,
      timeline: 'tl',
      at: '42',
    })
    // No dimension in the time context: the whole vault.
    expect(graphQuery(DEFAULT_FILTERS, null, undefined)).toEqual({})
  })

  it('are saved as named views, and layouts per view', () => {
    expect(readViews('v1')).toEqual([])
    writeViews('v1', [{ name: 'Family', filters: { ...DEFAULT_FILTERS, kinds: ['character'] } }])
    expect(readViews('v1')[0]?.filters.kinds).toEqual(['character'])
    localStorage.setItem('lore.graph.views.v1', 'not json')
    expect(readViews('v1')).toEqual([])
    writePositions('v1', 'k', { a: [1, 2] })
    expect(readPositions('v1', 'k')).toEqual({ a: [1, 2] })
    expect(readPositions('v1', 'other')).toEqual({})
  })
})

describe('graph styles', () => {
  it('put edges in categories', () => {
    expect(edgeCategory({ kind: 'mention', link_type: null })).toBe('mention')
    expect(edgeCategory({ kind: 'parent', link_type: null })).toBe('hierarchy')
    expect(edgeCategory({ kind: 'link', link_type: 'characters.spouse_of' })).toBe('family')
    expect(edgeCategory({ kind: 'link', link_type: 'characters.rival_of' })).toBe('social')
    expect(edgeCategory({ kind: 'link', link_type: 'locations.resides_in' })).toBe('spatial')
    expect(edgeCategory({ kind: 'link', link_type: 'core.causes' })).toBe('causal')
    expect(edgeCategory({ kind: 'link', link_type: 'core.related' })).toBe('other')
  })

  it('let modules style kinds and link types (graphStyles)', () => {
    const styles = mergeStyles([
      { nodes: { relic: { color: '#111111' } } },
      { edges: { 'core.related': { color: '#222222', size: 3 } } },
      undefined,
    ])
    expect(nodeColor('relic', undefined, styles)).toBe('#111111')
    expect(nodeColor('other', undefined, styles)).toBe('#64748b')
    const related = edgeStyle(
      { kind: 'link', link_type: 'core.related', weight: 1 },
      undefined,
      styles,
    )
    expect(related).toEqual({ category: 'other', color: '#222222', size: 3 })
    const mention = edgeStyle({ kind: 'mention', link_type: null, weight: 4 }, undefined, styles)
    expect(mention.color).toBe(CATEGORY_COLORS.mention)
    expect(mention.size).toBe(3) // 1 + log2(4)
  })
})
