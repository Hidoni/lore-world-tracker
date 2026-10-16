import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { CAPS, defaultRows, FIELD, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const MISC = kind('misc', 'Misc entry', {
  module: 'misc',
  plural: 'Misc entries',
  icon: 'shapes',
  allowed_parents: ['misc'],
  capabilities: { ...CAPS, can_be_multiversal: true },
  fields: [{ ...FIELD, key: 'category', label: 'Category' }],
})
// Artifacts may live in misc entries, like every non-system kind.
const ARTIFACT = { ...KINDS[1], allowed_parents: ['artifact', 'misc'] }
const EVENT = kind('event', 'Event', {
  allowed_parents: ['event', 'misc'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})

/** Atlas with the misc module: "Time Travel" holds misc entries, artifacts and an event. */
function world(enabled = true) {
  return serveVault({
    modules: ['misc'],
    ...(enabled ? {} : { moduleStates: [] }),
    kinds: [KINDS[0], ARTIFACT, EVENT, MISC],
    rows: [
      ...defaultRows(),
      row('tt', 'misc', 'Time Travel', { dimension_id: null, fields: { category: 'Concept' } }),
      row('gp', 'misc', 'Grandfather Paradox', {
        parent_id: 'tt',
        fields: { category: 'Concept' },
      }),
      row('cl', 'artifact', 'Chronolith', { parent_id: 'tt' }),
      row('jump', 'event', 'The First Jump', { parent_id: 'tt' }),
      row('tm', 'misc', 'Tide Magic', { fields: { category: 'Magic' } }),
      row('loose', 'misc', 'Loose Ends'),
      row('ai', 'misc', 'Artificers', { fields: { category: 'concept' } }),
      row('wh', 'misc', 'Wormholes', { fields: { category: 'Concept' } }),
    ],
  })
}

const sidebar = () => screen.getByRole('navigation', { name: 'Vault' })

describe('misc module', () => {
  it('groups the sidebar section by category, then by tree', async () => {
    world()
    await renderApp('/v/v1')
    const section = await within(sidebar()).findByRole('region', { name: 'Misc entries' })
    const concept = await within(section).findByRole('list', { name: 'Concept' })
    // Case variants share a group under the most used spelling; within it the tree's order.
    expect(
      within(concept)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['Artificers', 'Time Travel', 'Wormholes'])
    expect(
      within(section)
        .getAllByRole('list')
        .map((list) => list.getAttribute('aria-label'))
        .filter((label) => label !== null),
    ).toEqual(['Concept', 'Magic', 'No category'])
    expect(
      within(within(section).getByRole('list', { name: 'No category' })).getByRole('link', {
        name: 'Loose Ends',
      }),
    ).toBeInTheDocument()
    // Children nest under their parent as usual.
    await userEvent.click(within(concept).getByRole('button', { name: 'Expand Time Travel' }))
    expect(
      await within(concept).findByRole('link', { name: 'Grandfather Paradox' }),
    ).toBeInTheDocument()
  })

  it('lists the children of every kind on the page, grouped by kind, and adds children', async () => {
    const writes = world()
    await renderApp('/v/v1/e/tt')
    const panel = await screen.findByRole('region', { name: 'Children' })
    const groups = await within(panel).findAllByRole('region')
    expect(groups.map((group) => group.getAttribute('aria-label'))).toEqual([
      'Artifacts',
      'Events',
      'Misc entries',
    ])
    expect(within(panel).getByRole('link', { name: 'The First Jump' })).toHaveAttribute(
      'href',
      '/v/v1/e/jump',
    )

    await userEvent.click(within(panel).getByRole('button', { name: 'Add child' }))
    const menu = await screen.findByRole('menu')
    expect(
      within(menu)
        .getAllByRole('menuitem')
        .map((item) => item.textContent),
    ).toEqual([' Artifact', ' Event', ' Misc entry'])
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Artifact' }))
    const dialog = await screen.findByRole('dialog', { name: 'New artifact' })
    expect(within(dialog).getByRole('radio', { name: 'Time Travel' })).toBeChecked()
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Hourglass')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        body: { kind: 'artifact', name: 'Hourglass', parent_id: 'tt' },
      })
    })
  })

  it('says when an entry is empty', async () => {
    world()
    await renderApp('/v/v1/e/loose')
    const panel = await screen.findByRole('region', { name: 'Children' })
    expect(await within(panel).findByText('Nothing is inside Loose Ends yet.')).toBeInTheDocument()
  })

  it('suggests categories other entries use', async () => {
    world()
    await renderApp('/v/v1/e/loose')
    const fields = await screen.findByRole('region', { name: 'Fields' })
    await userEvent.click(within(fields).getByRole('button', { name: 'Edit Category' }))
    const input = within(fields).getByRole('combobox', { name: 'Category' })
    const list = document.getElementById(input.getAttribute('list') ?? '')
    await waitFor(() => {
      expect([...(list?.querySelectorAll('option') ?? [])].map((option) => option.value)).toEqual([
        'Concept',
        'concept',
        'Magic',
      ])
    })
  })
})

describe('misc pages in reader mode', () => {
  it.each(['/v/v1/e/tt', '/v/v1/e/loose'])(
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

describe('misc pages for the author', () => {
  it.each(['/v/v1/e/tt', '/v/v1/e/loose'])(
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
