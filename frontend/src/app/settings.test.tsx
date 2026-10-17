import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { defineModule } from '@/core/modules'
import { linkType, serveVault, type ModuleStateRow } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const module = (id: string, name: string, extra: Partial<ModuleStateRow> = {}) => ({
  id,
  name,
  description: `${name} things.`,
  depends_on: [],
  default_enabled: true,
  enabled: true,
  ...extra,
})

describe('modules settings', () => {
  const states = () => [
    module('places', 'Places', { enabled: false }),
    module('maps', 'Maps', { depends_on: ['places'], enabled: false }),
    module('lexicon', 'Lexicon'),
    module('scripts', 'Scripts', { depends_on: ['lexicon'] }),
  ]

  it('asks before enabling a module’s dependencies', async () => {
    const writes = serveVault({ moduleStates: states() })
    await renderApp('/v/v1/settings/modules')
    await userEvent.click(await screen.findByRole('switch', { name: 'Maps' }))
    const dialog = await screen.findByRole('dialog', { name: 'Enable Maps?' })
    expect(within(dialog).getByRole('listitem')).toHaveTextContent('Places')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Enable all' }))
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Maps' })).toBeChecked()
    })
    expect(screen.getByRole('switch', { name: 'Places' })).toBeChecked()
    expect(writes.at(-1)).toMatchObject({ path: '/modules/maps', body: { enabled: true } })
    expect(await screen.findByText('Enabled Places, Maps')).toBeInTheDocument()
  })

  it('asks before disabling the modules that depend on one, then cascades', async () => {
    const writes = serveVault({ moduleStates: states() })
    await renderApp('/v/v1/settings/modules')
    await userEvent.click(await screen.findByRole('switch', { name: 'Lexicon' }))
    const dialog = await screen.findByRole('dialog', { name: 'Disable Lexicon?' })
    expect(within(dialog).getByRole('listitem')).toHaveTextContent('Scripts')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(writes).toEqual([])
    await userEvent.click(screen.getByRole('switch', { name: 'Lexicon' }))
    await userEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Disable all' }),
    )
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Scripts' })).not.toBeChecked()
    })
    expect(writes.at(-1)).toMatchObject({
      path: '/modules/lexicon',
      body: { enabled: false, cascade: true },
    })
  })

  it('disables a module nothing needs at once, and asks again when the server says otherwise', async () => {
    const writes = serveVault({
      moduleStates: [
        module('lexicon', 'Lexicon'),
        // The page sees Scripts off; the server knows it's on (enabled meanwhile).
        module('scripts', 'Scripts', { depends_on: ['lexicon'] }),
      ],
    })
    await renderApp('/v/v1/settings/modules')
    await userEvent.click(await screen.findByRole('switch', { name: 'Scripts' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ path: '/modules/scripts', body: { enabled: false } })
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('link types settings', () => {
  const vault = () =>
    serveVault({
      linkTypes: [
        linkType('core.related', 'related to', { symmetric: true }),
        {
          ...linkType('custom.rival_of', 'rival of', { inverse_label: 'rivalled by' }),
          user_defined: true,
          revision: 1,
        },
      ],
      links: [{ id: 'l1', link_type: 'custom.rival_of', source_id: 'a1', target_id: 'a3' }],
    })

  it('lists built-in types read-only and creates, edits and archives custom ones', async () => {
    const writes = vault()
    await renderApp('/v/v1/settings/link-types')
    const builtIn = await screen.findByRole('list', { name: 'Built-in link types' })
    expect(within(builtIn).getByText('related to')).toBeInTheDocument()
    expect(within(builtIn).queryByRole('button')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'New link type' }))
    const dialog = await screen.findByRole('dialog', { name: 'New link type' })
    await userEvent.type(within(dialog).getByLabelText('Label'), 'forged in')
    await userEvent.type(within(dialog).getByLabelText('Inverse label'), 'forge of')
    expect(
      within(dialog).getByText('Read as “A forged in B”, and back as “B forge of A”.'),
    ).toBeInTheDocument()
    const from = within(dialog).getByRole('group', { name: 'From' })
    await userEvent.click(within(from).getByLabelText('Any kind'))
    await userEvent.click(within(from).getByLabelText('Artifact'))
    const to = within(dialog).getByRole('group', { name: 'To' })
    await userEvent.click(within(to).getByLabelText('Any kind'))
    expect(within(dialog).getByText('Choose at least one target kind.')).toBeInTheDocument()
    await userEvent.click(within(to).getByLabelText('Dimension'))
    await userEvent.selectOptions(within(dialog).getByLabelText('Repeats'), 'One per pair')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(writes.at(-1)).toMatchObject({
      method: 'POST',
      path: '/link-types',
      body: {
        label: 'forged in',
        inverse_label: 'forge of',
        source_kinds: ['artifact'],
        target_kinds: ['dimension'],
        symmetric: false,
        temporal: 'optional',
        unique: 'per_pair',
      },
    })
    const custom = await screen.findByRole('list', { name: 'Custom link types' })
    await within(custom).findByText('forged in')

    await userEvent.click(within(custom).getByRole('button', { name: 'Edit rival of' }))
    const edit = await screen.findByRole('dialog', { name: 'Edit rival of' })
    expect(within(edit).getByLabelText(/Symmetric/)).toBeDisabled()
    await userEvent.clear(within(edit).getByLabelText('Label'))
    await userEvent.type(within(edit).getByLabelText('Label'), 'arch rival of')
    await userEvent.click(within(edit).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/link-types/custom.rival_of',
        body: { label: 'arch rival of', revision: 1 },
      })
    })
    await userEvent.click(
      await within(custom).findByRole('button', { name: 'Archive arch rival of' }),
    )
    expect(await within(custom).findByText('Archived')).toBeInTheDocument()
    expect(writes.at(-1)).toMatchObject({ body: { archived: true, revision: 2 } })
  })

  it('explains why a used link type can’t be deleted', async () => {
    vault()
    await renderApp('/v/v1/settings/link-types')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete rival of' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '1 links use this link type. Archive it instead',
    )
  })
})

describe('general and backups settings', () => {
  it('sets the default visibility', async () => {
    const writes = serveVault()
    await renderApp('/v/v1/settings')
    const select = await screen.findByLabelText('Default visibility')
    await waitFor(() => {
      expect(select).toBeEnabled()
    })
    await userEvent.selectOptions(select, 'Private: authors only')
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/settings',
        body: { defaults: { visibility: 'private' } },
      })
    })
  })

  it('backs up, schedules and restores with the private-data notice', async () => {
    const writes = serveVault({ restoreFailures: 1 })
    await renderApp('/v/v1/settings/backups')
    expect(await screen.findByRole('note')).toHaveTextContent('Backups contain everything')
    await userEvent.click(screen.getByLabelText('Include media files'))
    await userEvent.click(screen.getByRole('button', { name: 'Back up now' }))
    const list = await screen.findByRole('list', { name: 'Backups list' })
    expect(within(list).getByRole('listitem')).toHaveTextContent('Manual · 2.0 KB · without media')
    expect(within(list).getByRole('link', { name: 'Download' })).toHaveAttribute(
      'href',
      '/api/v1/vaults/v1/backups/b1/download',
    )
    expect(writes.at(-1)).toMatchObject({ body: { include_media: false } })

    const every = screen.getByLabelText('Every (hours)')
    await userEvent.clear(every)
    await userEvent.type(every, '-1')
    expect(screen.getByText(/Use whole numbers/)).toBeInTheDocument()
    await userEvent.clear(every)
    await userEvent.type(every, '12')
    await userEvent.click(screen.getByRole('button', { name: 'Save schedule' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        path: '/settings',
        body: { backups: { every_hours: 12, keep: 7, include_media: true } },
      })
    })

    await userEvent.upload(
      screen.getByLabelText('Backup zip'),
      new File(['zip'], 'bad.zip', { type: 'application/zip' }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Restore into a new vault' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This file isn’t a Lore backup.')
    await userEvent.upload(
      screen.getByLabelText('Backup zip'),
      new File(['zip'], 'atlas.zip', { type: 'application/zip' }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Restore into a new vault' }))
    expect(await screen.findByRole('link', { name: 'Atlas (restored)' })).toHaveAttribute(
      'href',
      '/v/v9',
    )
  })
})

describe('publishing settings', () => {
  it('publishes a snapshot and shows when', async () => {
    const writes = serveVault()
    await renderApp('/v/v1/settings/publishing')
    expect(await screen.findByText('Not published yet.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Publish snapshot' }))
    expect(await screen.findByText(/Last published/)).toBeInTheDocument()
    expect(writes.at(-1)).toMatchObject({ method: 'POST', path: '/publish' })
  })

  it('explains when the server has no publish directory', async () => {
    serveVault({ publishable: false })
    await renderApp('/v/v1/settings/publishing')
    expect(await screen.findByText(/Publishing isn’t set up/)).toHaveTextContent('LORE_PUBLISH_DIR')
    expect(screen.queryByRole('button', { name: 'Publish snapshot' })).not.toBeInTheDocument()
  })

  it('links the Markdown exports', async () => {
    serveVault()
    await renderApp('/v/v1/settings/publishing')
    expect(await screen.findByRole('link', { name: 'Download readers’ view' })).toHaveAttribute(
      'href',
      '/api/v1/vaults/v1/export/markdown?audience=readers',
    )
    expect(screen.getByRole('link', { name: 'Download everything' })).toHaveAttribute(
      'href',
      '/api/v1/vaults/v1/export/markdown?audience=author',
    )
  })
})

describe('module settings pages', () => {
  it('lists them in the settings navigation', async () => {
    serveVault({ modules: ['maps'] })
    const maps = defineModule({
      id: 'maps',
      settingsPages: [{ id: 'maps', title: 'Map tiles', component: () => <p>Tile server URL</p> }],
    })
    await renderApp('/v/v1/settings', [maps])
    const nav = await screen.findByRole('navigation', { name: 'Settings' })
    await userEvent.click(within(nav).getByRole('link', { name: 'Map tiles' }))
    expect(await screen.findByText('Tile server URL')).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Map tiles' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})
