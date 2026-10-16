import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { DescentTree } from '@/data'
import { layoutDescent, layoutEdges } from '@/modules/species/views/layout'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { defaultRows, kind, KINDS, linkType, row, serveVault } from '@/test/fake-vault'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }
/** The first layout loads ELK, which can take a while under a loaded test run. */
const LAID_OUT = { timeout: 10_000 }

const LINK_TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('species.is_a', 'is a', { module: 'species', inverse_label: 'members' }),
  linkType('species.descended_from', 'descended from', {
    module: 'species',
    inverse_label: 'ancestor of',
  }),
  linkType('species.native_to', 'native to', { module: 'species' }),
]

function world() {
  return serveVault({
    modules: ['species'],
    kinds: [
      KINDS[0],
      KINDS[1],
      kind('species', 'Species', { module: 'species', icon: 'dna', allowed_parents: ['species'] }),
      kind('character', 'Character'),
      kind('location', 'Location'),
    ],
    linkTypes: LINK_TYPES,
    rows: [
      ...defaultRows(),
      row('first', 'species', 'First Folk'),
      row('elves', 'species', 'Elves'),
      row('sea', 'species', 'Sea Elves', { parent_id: 'elves' }),
      row('ilsa', 'character', 'Ilsa'),
      row('varn', 'location', 'Varn'),
    ],
    links: [
      { id: 'd1', link_type: 'species.descended_from', source_id: 'elves', target_id: 'first' },
      { id: 'i1', link_type: 'species.is_a', source_id: 'ilsa', target_id: 'elves' },
      { id: 'n1', link_type: 'species.native_to', source_id: 'elves', target_id: 'varn' },
    ],
  })
}

describe('species module', () => {
  it('shows members, descent and native lands', async () => {
    world()
    await renderApp('/v/v1/e/elves')
    const members = await screen.findByRole('region', { name: 'Members' }, WAIT)
    expect(await within(members).findByRole('link', { name: 'Ilsa' }, WAIT)).toBeVisible()
    const descent = screen.getByRole('region', { name: 'Descent' })
    expect(await within(descent).findByRole('list', { name: 'Descended from' })).toHaveTextContent(
      'First Folk',
    )
    expect(within(descent).getByRole('list', { name: 'Subspecies' })).toHaveTextContent('Sea Elves')
    const native = screen.getByRole('region', { name: 'Native to' })
    expect(await within(native).findByRole('link', { name: 'Varn' })).toBeVisible()
  })

  it('shows a character’s species in the header', async () => {
    world()
    await renderApp('/v/v1/e/ilsa')
    const chips = await screen.findByRole('list', { name: 'Species' }, WAIT)
    expect(within(chips).getByRole('link', { name: 'Elves' })).toHaveAttribute(
      'href',
      '/v/v1/e/elves',
    )
  })

  it('draws the descent tree, with a list alternative', async () => {
    world()
    await renderApp('/v/v1/m/species/descent-tree')
    const figure = await screen.findByRole('figure', { name: 'Species descent tree' }, WAIT)
    await waitFor(() => {
      expect(within(figure).getAllByTestId('descent-node')).toHaveLength(3)
    }, LAID_OUT)
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    expect(screen.getAllByTestId('descent-item').map((item) => item.textContent)).toEqual([
      'Elves · descended from First Folk',
      'First Folk',
      'Sea Elves · subspecies of Elves',
    ])
  })
})

describe('descent layout', () => {
  it('layers ancestors above descendants and subspecies', async () => {
    const tree = {
      nodes: ['first', 'elves', 'sea'].map((id) => ({
        id,
        name: id,
        visibility: 'public',
        dimension_id: null,
        parent_id: null,
      })),
      edges: [
        { id: 'd1', kind: 'descended_from', source_id: 'elves', target_id: 'first' },
        { id: 'subspecies:sea', kind: 'subspecies', source_id: 'sea', target_id: 'elves' },
      ],
      truncated: false,
    } as DescentTree
    expect(layoutEdges(tree).map((edge) => [edge.sources[0], edge.targets[0]])).toEqual([
      ['first', 'elves'],
      ['elves', 'sea'],
    ])
    const positions = await layoutDescent(tree)
    const y = (id: string) => positions.get(id)?.y ?? Number.NaN
    expect(y('first')).toBeLessThan(y('elves'))
    expect(y('elves')).toBeLessThan(y('sea'))
  })
})

describe('species pages in reader mode', () => {
  it.each(['/v/v1/e/elves', '/v/v1/m/species/descent-tree'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})

describe('species pages for the author', () => {
  it.each(['/v/v1/e/elves', '/v/v1/m/species/descent-tree'])(
    '%s is accessible',
    async (path) => {
      world()
      await renderApp(path)
      await settled()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})
