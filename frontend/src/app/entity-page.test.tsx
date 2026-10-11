import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { CAPS, FIELD, kind, serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

beforeEach(() => {
  localStorage.clear()
})

describe('entity page', () => {
  it('renders a kind with no module UI from the registry alone', async () => {
    serveVault()
    await renderApp('/v/v1/e/a1')
    expect(await screen.findByRole('heading', { name: 'Crown', level: 1 })).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumbs' })
    expect(await within(crumbs).findByRole('link', { name: 'Treasury' })).toHaveAttribute(
      'href',
      '/v/v1/e/a2',
    )
    expect(screen.getByText('Artifact')).toBeInTheDocument()
    expect(await screen.findByText('Aetheria')).toBeInTheDocument() // its dimension
    const fields = screen.getByRole('region', { name: 'Fields' })
    expect(within(fields).getByText('Era')).toBeInTheDocument()
    expect(within(fields).getByText('Origin')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Body' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Relations' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Time' })).not.toBeInTheDocument()
    expect(
      within(screen.getByRole('group', { name: 'Aliases' })).getByText('Diadem'),
    ).toBeInTheDocument()
  })

  it('renames inline, edits aliases and tags, and sets the visibility', async () => {
    const writes = serveVault()
    const user = userEvent.setup()
    await renderApp('/v/v1/e/a1')
    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    const name = screen.getByRole('textbox', { name: 'Name' })
    await user.clear(name)
    await user.type(name, 'Iron Crown{Enter}')
    expect(await screen.findByRole('heading', { name: 'Iron Crown', level: 1 })).toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: 'Add tags' }), 'regalia{Enter}')
    expect(
      await within(screen.getByRole('group', { name: 'Tags' })).findByText('regalia'),
    ).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: 'Add aliases' }), 'Circlet{Enter}')
    await within(screen.getByRole('group', { name: 'Aliases' })).findByText('Circlet')
    await user.click(screen.getByRole('button', { name: 'Remove Diadem' }))
    await waitFor(() => {
      expect(
        within(screen.getByRole('group', { name: 'Aliases' })).queryByText('Diadem'),
      ).not.toBeInTheDocument()
    })

    await user.click(screen.getByRole('combobox', { name: 'Visibility' }))
    await user.click(await screen.findByRole('option', { name: 'Spoiler' }))
    await waitFor(() => {
      expect(writes).toHaveLength(5)
    })
    expect(writes.map((write) => write.body)).toEqual([
      { name: 'Iron Crown', revision: 1 },
      { tags: ['regalia'], revision: 2 },
      {
        aliases: [
          { id: 'al1', alias: 'Diadem', alias_kind: 'alias', visibility: 'public' },
          { alias: 'Circlet' },
        ],
        revision: 3,
      },
      {
        aliases: [{ id: 'new1', alias: 'Circlet', alias_kind: 'alias', visibility: 'public' }],
        revision: 4,
      },
      { visibility: 'spoiler', revision: 5 },
    ])
  })

  it('moves to the trash with a children warning, restores and purges', async () => {
    const writes = serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1/e/a1')
    await user.click(await screen.findByRole('button', { name: 'More actions' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Move to trash' }))
    const dialog = await screen.findByRole('dialog', { name: 'Move “Crown” to the trash?' })
    expect(await within(dialog).findByText(/It has children/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Move to trash' }))
    expect(await screen.findByText('This entity is in the trash.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Restore' }))
    await waitFor(() => {
      expect(screen.queryByText('This entity is in the trash.')).not.toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'More actions' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Move to trash' }))
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Move to trash' }),
    )
    await user.click(await screen.findByRole('button', { name: 'Delete permanently' }))
    const confirm = await screen.findByRole('dialog', { name: 'Delete “Crown” permanently?' })
    await user.click(within(confirm).getByRole('button', { name: 'Delete permanently' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1')
    })
    expect(writes.map((write) => `${write.method} ${write.path}`)).toEqual([
      'DELETE /entities/a1',
      'POST /entities/a1/restore',
      'DELETE /entities/a1',
      'DELETE /entities/a1?purge=true',
    ])
  })

  it('creates an entity from the New… menu with a parent of an allowed kind', async () => {
    const writes = serveVault()
    const user = userEvent.setup()
    const { router } = await renderApp('/v/v1')
    await user.click(await screen.findByRole('button', { name: 'New…' }))
    expect(screen.queryByRole('menuitem', { name: 'Dimension' })).not.toBeInTheDocument() // system kind
    await user.click(await screen.findByRole('menuitem', { name: 'Artifact' }))
    const dialog = await screen.findByRole('dialog', { name: 'New artifact' })
    await user.type(within(dialog).getByLabelText('Name'), 'Scepter')
    const dimension = within(dialog).getByLabelText('Dimension')
    expect(
      within(dimension)
        .getAllByRole('option')
        .map((option) => option.textContent),
    ).toEqual(['Multiversal (every dimension)', 'Aetheria'])
    await user.selectOptions(dimension, 'd1')
    const parents = within(dialog).getByRole('list', { name: 'Parents' })
    await user.click(await within(parents).findByRole('radio', { name: 'Treasury' }))
    await user.click(within(dialog).getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/new1')
    })
    expect(await screen.findByRole('heading', { name: 'Scepter', level: 1 })).toBeInTheDocument()
    expect(writes[0]).toEqual({
      method: 'POST',
      path: '/entities',
      body: { kind: 'artifact', name: 'Scepter', dimension_id: 'd1', parent_id: 'a2' },
    })
  })

  it('asks for required fields in the create dialog and validates them', async () => {
    const writes = serveVault({
      kinds: [
        kind('dimension', 'Dimension', { capabilities: { ...CAPS, is_system: true } }),
        kind('ship', 'Ship', {
          fields: [
            { ...FIELD, key: 'crew', label: 'Crew', type: 'integer', required: true },
            { ...FIELD, key: 'flag', label: 'Flag', type: 'text' },
          ],
        }),
      ],
    })
    const user = userEvent.setup()
    await renderApp('/v/v1')
    await user.click(await screen.findByRole('button', { name: 'New…' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Ship' }))
    const dialog = await screen.findByRole('dialog', { name: 'New ship' })
    expect(within(dialog).queryByLabelText('Flag')).not.toBeInTheDocument() // optional
    await user.click(within(dialog).getByRole('button', { name: 'Create' }))
    expect(await within(dialog).findByText('A name is required')).toBeInTheDocument()
    expect(within(dialog).getByText('Required')).toBeInTheDocument()

    await user.type(within(dialog).getByLabelText('Name'), 'Argo')
    await user.type(within(dialog).getByLabelText('Crew'), 'fifty')
    await user.click(within(dialog).getByRole('button', { name: 'Create' }))
    expect(await within(dialog).findByText(/Must be a whole number/)).toBeInTheDocument()
    expect(writes).toEqual([])

    await user.clear(within(dialog).getByLabelText('Crew'))
    await user.type(within(dialog).getByLabelText('Crew'), '50')
    await user.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(writes).toHaveLength(1)
    })
    expect(writes[0]?.body).toEqual({
      kind: 'ship',
      name: 'Argo',
      dimension_id: 'd1',
      parent_id: null,
      fields: { crew: '50' },
    })
  })

  it('shows no editing UI without Mutations (reader mode)', async () => {
    serveVault()
    await renderApp('/v/v1/e/a1', undefined, { readOnly: true })
    expect(await screen.findByRole('heading', { name: 'Crown', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'More actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Visibility' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Add tags' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New…' })).not.toBeInTheDocument()
  })
})
