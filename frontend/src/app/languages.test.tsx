import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { FamilyTree } from '@/data'
import { layoutEdges, layoutFamily } from '@/modules/languages/views/layout'
import { expectAccessible } from '@/test/axe'
import { defaultRows, kind, KINDS, linkType, row, serveVault } from '@/test/fake-vault'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }
/** The first layout loads ELK, which can take a while under a loaded test run. */
const LAID_OUT = { timeout: 10_000 }

const languages = { module: 'languages', source_kinds: ['language'], target_kinds: ['language'] }
const LINK_TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('languages.descended_from', 'descended from', {
    ...languages,
    inverse_label: 'ancestor of',
  }),
  linkType('languages.borrowed_from', 'borrows from', { ...languages, inverse_label: 'lends to' }),
  linkType('languages.uses_script', 'written in', {
    module: 'languages',
    inverse_label: 'used by',
  }),
  linkType('languages.speaks', 'speaks', { module: 'languages', inverse_label: 'spoken by' }),
]

function world() {
  return serveVault({
    modules: ['languages'],
    kinds: [
      KINDS[0],
      KINDS[1],
      kind('language', 'Language', {
        module: 'languages',
        icon: 'languages',
        allowed_parents: ['language'],
      }),
      kind('writing_system', 'Writing system', { module: 'languages', icon: 'type' }),
      kind('character', 'Character'),
    ],
    linkTypes: LINK_TYPES,
    rows: [
      ...defaultRows(),
      row('old', 'language', 'Old Varnish'),
      row('varnish', 'language', 'Varnish'),
      row('cant', 'language', 'Harbor Cant', { parent_id: 'varnish' }),
      row('common', 'language', 'Common'),
      row('runes', 'writing_system', 'Tide Runes'),
      row('ilsa', 'character', 'Ilsa'),
    ],
    links: [
      { id: 'd1', link_type: 'languages.descended_from', source_id: 'varnish', target_id: 'old' },
      {
        id: 'b1',
        link_type: 'languages.borrowed_from',
        source_id: 'varnish',
        target_id: 'common',
        data: { note: 'trade words' },
      },
      { id: 's1', link_type: 'languages.uses_script', source_id: 'varnish', target_id: 'runes' },
      {
        id: 'p1',
        link_type: 'languages.speaks',
        source_id: 'ilsa',
        target_id: 'varnish',
        data: { fluency: 'native' },
      },
    ],
  })
}

describe('languages module', () => {
  it('shows a language’s family, speakers and scripts', async () => {
    world()
    await renderApp('/v/v1/e/varnish')
    const family = await screen.findByRole('region', { name: 'Family' }, WAIT)
    expect(
      await within(family).findByRole('list', { name: 'Descended from' }, WAIT),
    ).toHaveTextContent('Old Varnish')
    expect(await within(family).findByRole('list', { name: 'Dialects' })).toHaveTextContent(
      'Harbor Cant',
    )
    expect(within(family).getByRole('list', { name: 'Borrows from' })).toHaveTextContent(
      'Common (trade words)',
    )
    const speakers = screen.getByRole('region', { name: 'Speakers' })
    expect(await within(speakers).findByRole('listitem')).toHaveTextContent('Ilsa (native)')
    const scripts = screen.getByRole('region', { name: 'Scripts' })
    expect(await within(scripts).findByRole('link', { name: 'Tide Runes' })).toBeVisible()
  })

  it('lists the languages a writing system writes', async () => {
    world()
    await renderApp('/v/v1/e/runes')
    const scripts = await screen.findByRole('region', { name: 'Scripts' }, WAIT)
    expect(await within(scripts).findByRole('link', { name: 'Varnish' }, WAIT)).toBeVisible()
  })

  it('draws the family tree, with a list alternative', async () => {
    world()
    await renderApp('/v/v1/m/languages/family-tree')
    const figure = await screen.findByRole('figure', { name: 'Language family tree' }, WAIT)
    await waitFor(() => {
      expect(within(figure).getAllByTestId('family-node')).toHaveLength(4)
    }, LAID_OUT)
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    expect(screen.getAllByTestId('family-item').map((item) => item.textContent)).toEqual([
      'Common',
      'Harbor Cant · dialect of Varnish',
      'Old Varnish',
      'Varnish · descended from Old Varnish · borrows from Common',
    ])
  })
})

describe('family layout', () => {
  const tree = {
    nodes: ['old', 'varnish', 'cant', 'common'].map((id) => ({
      id,
      name: id,
      visibility: 'public',
      dimension_id: null,
      parent_id: null,
    })),
    edges: [
      { id: 'd1', kind: 'descended_from', source_id: 'varnish', target_id: 'old' },
      { id: 'b1', kind: 'borrowed_from', source_id: 'varnish', target_id: 'common' },
      { id: 'dialect:cant', kind: 'dialect', source_id: 'cant', target_id: 'varnish' },
    ],
    truncated: false,
  } as FamilyTree

  it('layers ancestors above descendants, leaving borrowings out', async () => {
    expect(layoutEdges(tree).map((edge) => [edge.sources[0], edge.targets[0]])).toEqual([
      ['old', 'varnish'],
      ['varnish', 'cant'],
    ])
    const positions = await layoutFamily(tree)
    const y = (id: string) => positions.get(id)?.y ?? Number.NaN
    expect(y('old')).toBeLessThan(y('varnish'))
    expect(y('varnish')).toBeLessThan(y('cant'))
  })
})

describe('languages pages in reader mode', () => {
  it.each(['/v/v1/e/varnish', '/v/v1/e/runes', '/v/v1/m/languages/family-tree'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
      await expectAccessible()
    },
  )
})

describe('languages pages for the author', () => {
  it.each(['/v/v1/e/varnish', '/v/v1/e/runes', '/v/v1/m/languages/family-tree'])(
    '%s is accessible',
    async (path) => {
      world()
      await renderApp(path)
      await settled()
      await expectAccessible()
    },
  )
})
