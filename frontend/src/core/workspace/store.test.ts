import { beforeEach, describe, expect, it } from 'vitest'

import { routeOf } from './links'
import { MAX_PANES, useWorkspace } from './store'

const store = () => useWorkspace.getState()
const hrefs = () =>
  store().byVault.v1?.panes.map((pane) =>
    pane.tabs.map((tab) => `${tab.href}${tab.id === pane.active ? ' *' : ''}`),
  )

beforeEach(() => {
  store().reload()
})

describe('workspace store', () => {
  it('starts with one tab at the first page and moves it with the address bar', () => {
    store().follow('v1', '/v/v1')
    expect(hrefs()).toEqual([['/v/v1 *']])
    store().follow('v1', '/v/v1/e/a')
    expect(hrefs()).toEqual([['/v/v1/e/a *']])
    const main = store().byVault.v1?.panes[0]?.id ?? ''
    store().openTab('v1', main, '/v/v1/search')
    store().follow('v1', '/v/v1/e/a')
    // A page another tab shows switches to that tab.
    expect(hrefs()).toEqual([['/v/v1/e/a *', '/v/v1/search']])
  })

  it('opens tabs after the shown one and closes them to a neighbour', () => {
    store().follow('v1', '/v/v1/a')
    const main = store().byVault.v1?.panes[0]?.id ?? ''
    store().openTab('v1', main, '/v/v1/c')
    store().showTab('v1', main, store().byVault.v1?.panes[0]?.tabs[0]?.id ?? '')
    store().openTab('v1', main, '/v/v1/b')
    expect(hrefs()).toEqual([['/v/v1/a', '/v/v1/b *', '/v/v1/c']])
    store().closeTab('v1', main, store().byVault.v1?.panes[0]?.active ?? '')
    expect(hrefs()).toEqual([['/v/v1/a', '/v/v1/c *']])
    store().closeTab('v1', main, store().byVault.v1?.panes[0]?.active ?? '')
    store().closeTab('v1', main, store().byVault.v1?.panes[0]?.active ?? '')
    // The last tab of the last pane stays.
    expect(hrefs()).toEqual([['/v/v1/a *']])
  })

  it('splits up to MAX_PANES, then opens in the next pane; shares stay whole', () => {
    store().follow('v1', '/v/v1/0')
    for (let n = 1; n < MAX_PANES + 2; n++) {
      const panes = store().byVault.v1?.panes ?? []
      store().split('v1', panes.at(-1)?.id ?? '', `/v/v1/${String(n)}`)
    }
    expect(hrefs()).toEqual([
      ['/v/v1/0 *'],
      ['/v/v1/1 *'],
      ['/v/v1/2 *'],
      ['/v/v1/3', '/v/v1/4', '/v/v1/5 *'],
    ])
    const sizes = store().byVault.v1?.sizes ?? []
    expect(sizes.reduce((sum, size) => sum + size, 0)).toBeCloseTo(1)
    // A pane closes with its last tab, its share going to the others.
    const second = store().byVault.v1?.panes[1]
    store().closeTab('v1', second?.id ?? '', second?.active ?? '')
    expect(store().byVault.v1?.panes).toHaveLength(3)
    expect(store().byVault.v1?.sizes.reduce((sum, size) => sum + size, 0)).toBeCloseTo(1)
  })

  it('resizes within bounds and persists per vault', () => {
    store().follow('v1', '/v/v1')
    store().split('v1', store().byVault.v1?.panes[0]?.id ?? '', '/v/v1/e/a')
    store().resize('v1', 0, 0.2)
    expect(store().byVault.v1?.sizes[0]).toBeCloseTo(0.7)
    store().resize('v1', 0, 1)
    expect(store().byVault.v1?.sizes[0]).toBeCloseTo(0.85)
    store().reload()
    store().follow('v1', '/v/v1')
    expect(hrefs()).toEqual([['/v/v1 *'], ['/v/v1/e/a *']])
    expect(store().byVault.v1?.sizes[0]).toBeCloseTo(0.85)
    store().follow('v2', '/v/v2')
    expect(store().byVault.v2?.panes).toHaveLength(1)
  })

  it('ignores a stored workspace that does not parse', () => {
    localStorage.setItem('lore.workspace.v1', '{"panes": [{"id": 1}]}')
    store().follow('v1', '/v/v1')
    expect(hrefs()).toEqual([['/v/v1 *']])
  })
})

describe('routeOf', () => {
  const link = (href: string, attrs: Record<string, string> = {}) => {
    const anchor = document.createElement('a')
    anchor.setAttribute('href', href)
    for (const [key, value] of Object.entries(attrs)) anchor.setAttribute(key, value)
    return anchor
  }

  it('finds the vault route of a link', () => {
    expect(routeOf(link('/v/v1/e/a?tab=x'), 'v1')).toBe('/v/v1/e/a?tab=x')
    expect(routeOf(link('/v/v1'), 'v1')).toBe('/v/v1')
    expect(routeOf(link('#/v/v1/search?q=a'), 'v1')).toBe('/v/v1/search?q=a')
  })

  it('leaves other links alone', () => {
    expect(routeOf(link('/v/v2/e/a'), 'v1')).toBeNull()
    expect(routeOf(link('/v/v10'), 'v1')).toBeNull()
    expect(routeOf(link('#main'), 'v1')).toBeNull()
    expect(routeOf(link('https://example.com/v/v1'), 'v1')).toBeNull()
    expect(routeOf(link('/v/v1/e/a', { target: '_blank' }), 'v1')).toBeNull()
    expect(routeOf(link('/api/v1/vaults/v1/media/m', { download: '' }), 'v1')).toBeNull()
  })
})
