import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { serveVault, type FakeChangeset } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const doc = (text: string) => ({
  type: 'doc',
  content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
})
const crownRow = {
  kind: 'artifact',
  name: 'Crown',
  summary: '',
  fields: { era: 'First Age' },
  field_visibility: {},
  body: doc('old words'),
  parent_id: 'a2',
  deleted_at: null,
  revision: 3,
}
const CROWN = { id: 'a1', name: 'Crown', kind: 'artifact', exists: true }
const GEM = { id: 'a3', name: 'Gem', kind: 'artifact', exists: true }

const EDIT: FakeChangeset = {
  id: 'c3',
  summary: 'Edited “Diadem”',
  entities: [CROWN],
  changes: [
    {
      table_name: 'entities',
      row_id: 'a1',
      op: 'update',
      before: crownRow,
      after: {
        ...crownRow,
        name: 'Diadem',
        fields: { era: 'Second Age' },
        field_visibility: { era: 'private' },
        body: doc('three new words'),
        revision: 4,
      },
      entity_ids: ['a1'],
    },
    {
      table_name: 'entity_aliases',
      row_id: 'al9',
      op: 'insert',
      before: null,
      after: { entity_id: 'a1', alias: 'The Crown' },
      entity_ids: ['a1'],
    },
    {
      table_name: 'tags',
      row_id: 't1',
      op: 'insert',
      before: null,
      after: { name: 'royal' },
      entity_ids: [],
    },
    {
      table_name: 'entity_tags',
      row_id: 'a1:t1',
      op: 'insert',
      before: null,
      after: { entity_id: 'a1', tag_id: 't1' },
      entity_ids: ['a1'],
    },
  ],
}
const LINKED: FakeChangeset = {
  id: 'c2',
  summary: 'Added 1 link',
  entities: [CROWN, GEM],
  changes: [
    {
      table_name: 'links',
      row_id: 'l1',
      op: 'insert',
      before: null,
      after: { link_type: 'core.related', source_id: 'a1', target_id: 'a3', role: null },
      entity_ids: ['a1', 'a3'],
    },
  ],
}
const CREATED: FakeChangeset = {
  id: 'c1',
  summary: 'Created artifact “Crown”',
  origin: 'api',
  entities: [CROWN],
  changes: [
    {
      table_name: 'entities',
      row_id: 'a1',
      op: 'insert',
      before: null,
      after: crownRow,
      entity_ids: ['a1'],
    },
  ],
}

function vault(changesets: FakeChangeset[] = [EDIT, LINKED, CREATED]) {
  return serveVault({ changesets: changesets.map((changeset) => ({ ...changeset })) })
}

async function openHistory() {
  await userEvent.click(await screen.findByRole('tab', { name: 'History' }))
  return screen.findByRole('list', { name: 'Changes' })
}

const lines = (summary: string) =>
  within(screen.getByRole('list', { name: `Changes of “${summary}”` }))
    .getAllByRole('listitem')
    .map((item) => item.textContent)

describe('entity history', () => {
  it('lists the entity’s changesets with readable diffs', async () => {
    vault()
    await renderApp('/v/v1/e/a1')
    const list = await openHistory()
    expect(
      within(list)
        .getAllByRole('button', { name: /^Show the changes/ })
        .map((button) => button.getAttribute('aria-label')),
    ).toEqual([
      'Show the changes of “Edited “Diadem””',
      'Show the changes of “Added 1 link”',
      'Show the changes of “Created artifact “Crown””',
    ])
    await userEvent.click(
      within(list).getByRole('button', { name: /^Show the changes of “Edited “Diadem”/ }),
    )
    await screen.findByRole('list', { name: 'Changes of “Edited “Diadem””' })
    expect(lines('Edited “Diadem”')).toEqual([
      'NameCrown → Diadem',
      'EraFirst Age → Second Age',
      'Era visibilitydefault → private',
      'Body edited2 words → 3 words',
      'Alias added: The Crown',
      'Tagged royal',
    ])
    await userEvent.click(within(list).getByRole('button', { name: /^Show the changes of “Added/ }))
    await screen.findByRole('list', { name: 'Changes of “Added 1 link”' })
    // The other end is named (and the link type labelled from the registry).
    expect(lines('Added 1 link')).toEqual(['Linked: related to Gem'])
    expect(within(list).getAllByText('App')).toHaveLength(2)
    expect(within(list).getByText('API')).toBeInTheDocument()
  })

  it('undoes a changeset', async () => {
    const writes = vault()
    await renderApp('/v/v1/e/a1')
    const list = await openHistory()
    await userEvent.click(within(list).getByRole('button', { name: 'Undo “Edited “Diadem””' }))
    await waitFor(() => {
      expect(
        within(screen.getByRole('list', { name: 'Changes' })).getByText('Undone'),
      ).toBeInTheDocument()
    })
    expect(writes.at(-1)).toMatchObject({ method: 'POST', path: '/changes/c3/revert' })
    expect(
      within(screen.getByRole('list', { name: 'Changes' })).getByText('Undid “Edited “Diadem””'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo “Edited “Diadem””' })).not.toBeInTheDocument()
  })

  it('explains undo conflicts', async () => {
    vault([
      { ...EDIT, conflict: { rows: [{ table_name: 'entities', row_id: 'a1', op: 'update' }] } },
      {
        ...LINKED,
        conflict: { problems: [{ message: 'A gadget can’t be inside a misc' }] },
      },
    ])
    await renderApp('/v/v1/e/a1')
    const list = await openHistory()
    await userEvent.click(within(list).getByRole('button', { name: 'Undo “Edited “Diadem””' }))
    expect(await within(list).findByRole('alert')).toHaveTextContent(
      'This change can’t be undone: what it changed was changed again since. Undo the later changes first.',
    )
    await userEvent.click(within(list).getByRole('button', { name: 'Undo “Added 1 link”' }))
    await waitFor(() => {
      expect(within(list).getAllByRole('alert')).toHaveLength(2)
    })
    expect(within(list).getAllByRole('alert')[1]).toHaveTextContent(
      'Undoing this would break the vault’s rules:A gadget can’t be inside a misc',
    )
  })
})

describe('recent changes', () => {
  it('lists every change with its entities, filterable by origin', async () => {
    vault()
    const { router } = await renderApp('/v/v1/changes')
    const list = await screen.findByRole('list', { name: 'Changes' })
    expect(within(list).getAllByRole('listitem').length).toBeGreaterThanOrEqual(3)
    expect(within(list).getAllByRole('link', { name: 'Gem' })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'API' }))
    await waitFor(() => {
      expect(
        within(screen.getByRole('list', { name: 'Changes' })).getAllByRole('button', {
          name: /^Show the changes/,
        }),
      ).toHaveLength(1)
    })
    expect(router.state.location.search).toEqual({ origin: 'api' })
    expect(screen.getByRole('button', { name: 'API' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'API' }))
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('No changes from these origins.')).toBeInTheDocument()
    expect(router.state.location.search).toEqual({ origin: 'undo' })
  })
})

describe('undo the last change', () => {
  it('reverts the newest changeset from the palette', async () => {
    const writes = vault([{ ...EDIT, reverted_by_changeset_id: 'x' }, LINKED, CREATED])
    const user = userEvent.setup()
    await renderApp('/v/v1')
    await user.keyboard('{Control>}k{/Control}')
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' })
    await user.type(within(dialog).getByRole('combobox'), 'undo')
    await user.click(within(dialog).getByRole('option', { name: 'Undo the last change' }))
    expect(await screen.findByText('Undone: Added 1 link')).toBeInTheDocument()
    expect(writes.at(-1)).toMatchObject({ path: '/changes/c2/revert' })
  })
})
