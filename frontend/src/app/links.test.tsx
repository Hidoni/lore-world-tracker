import type { Editor } from '@tiptap/core'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import {
  KINDS,
  defaultRows,
  kind,
  linkType,
  row,
  serveVault,
  type LinkRow,
} from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const TYPES = [
  linkType('core.related', 'related to', { symmetric: true }),
  linkType('test.forged_in', 'forged in', {
    inverse_label: 'forge of',
    source_kinds: ['artifact'],
    target_kinds: ['dimension'],
  }),
  linkType('test.wields', 'wields', {
    inverse_label: 'wielded by',
    source_kinds: ['character'],
    target_kinds: ['artifact'],
    data_schema: {
      type: 'object',
      properties: {
        grip: { type: 'string', title: 'Grip' },
        cursed: { type: 'boolean', title: 'Cursed' },
      },
    },
  }),
  linkType('test.leads', 'leads', { source_kinds: ['character'], target_kinds: ['character'] }),
  linkType('test.old', 'old tie', { archived: true }),
]

const LINKS: LinkRow[] = [
  { id: 'l1', link_type: 'core.related', source_id: 'a1', target_id: 'a3' },
  {
    id: 'l2',
    link_type: 'test.forged_in',
    source_id: 'a1',
    target_id: 'd1',
    role: 'masterwork',
    visibility: 'spoiler',
  },
  {
    id: 'l3',
    link_type: 'test.wields',
    source_id: 'c1',
    target_id: 'a1',
    data: { grip: 'two-handed' },
  },
]

function vault(links: LinkRow[] = LINKS) {
  return serveVault({
    kinds: [...KINDS, kind('character', 'Character')],
    rows: [...defaultRows(), row('c1', 'character', 'Aria')],
    linkTypes: TYPES,
    links,
  })
}

const relations = () => screen.getByRole('region', { name: 'Relations' })
const group = (label: string) => within(relations()).getByRole('region', { name: label })
const names = (label: string) =>
  within(group(label))
    .getAllByRole('listitem')
    .map((item) => item.textContent)

describe('relations panel', () => {
  it('groups links by type with labels from the entity’s side, symmetric ones once', async () => {
    vault()
    await renderApp('/v/v1/e/a1')
    await screen.findByRole('region', { name: 'Relations' })
    await within(relations()).findByRole('link', { name: 'Gem' })
    expect(
      within(relations())
        .getAllByRole('heading', { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(['related to', 'forged in', 'wielded by'])
    expect(names('forged in')[0]).toMatch(/^Aetheriaas masterworkSpoiler/)
    expect(names('wielded by')[0]).toMatch(/^Ariagrip: two-handed/)
    await userEvent.click(within(relations()).getByRole('link', { name: 'Gem' }))
    await screen.findByRole('heading', { name: 'Gem' })
    await waitFor(() => {
      expect(names('related to')).toHaveLength(1)
    })
    expect(names('related to')[0]).toMatch(/^Crown/)
  })

  it('offers the link types that fit both kinds, in either direction', async () => {
    const writes = vault([])
    await renderApp('/v/v1/e/a1')
    await screen.findByRole('region', { name: 'Relations' })
    await userEvent.click(await within(relations()).findByRole('button', { name: 'Add link' }))
    const dialog = await screen.findByRole('dialog', { name: 'Link Crown' })
    const typeOptions = () =>
      within(within(dialog).getByLabelText('Link type'))
        .getAllByRole('option')
        .map((option) => option.textContent)
    // Before a target: everything an artifact can take part in (not archived types).
    expect(typeOptions()).toEqual(['forged in', 'related to', 'wielded by'])
    const pick = async (query: string, name: string) => {
      await userEvent.type(within(dialog).getByLabelText('Target'), query)
      await userEvent.click(await within(dialog).findByRole('button', { name: new RegExp(name) }))
    }
    await pick('Aeth', 'Aetheria')
    expect(typeOptions()).toEqual(['forged in', 'related to'])
    await userEvent.click(within(dialog).getByRole('button', { name: 'Change' }))
    await pick('Ge', 'Gem')
    expect(typeOptions()).toEqual(['related to'])
    await userEvent.click(within(dialog).getByRole('button', { name: 'Change' }))
    await pick('Ari', 'Aria')
    expect(typeOptions()).toEqual(['related to', 'wielded by'])

    await userEvent.selectOptions(within(dialog).getByLabelText('Link type'), 'wielded by')
    expect(within(dialog).getByText('Crown wielded by Aria')).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Grip'), 'one-handed')
    await userEvent.click(within(dialog).getByLabelText('Cursed'))
    await userEvent.type(within(dialog).getByLabelText('Role'), 'heirloom')
    await userEvent.selectOptions(within(dialog).getByLabelText('Visibility'), 'Private')
    // A timeless link type has no validity.
    expect(within(dialog).queryByText('Always')).toBeNull()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add link' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    // Reversed: Aria is the source of "wields".
    expect(writes.at(-1)).toMatchObject({
      method: 'POST',
      path: '/links',
      body: {
        link_type: 'test.wields',
        source_id: 'c1',
        target_id: 'a1',
        role: 'heirloom',
        data: { grip: 'one-handed', cursed: true },
        visibility: 'private',
      },
    })
    expect(await within(relations()).findByRole('link', { name: 'Aria' })).toBeInTheDocument()
  })

  it('edits and removes links', async () => {
    const writes = vault()
    await renderApp('/v/v1/e/a1')
    await screen.findByRole('region', { name: 'Relations' })
    await userEvent.click(
      await within(relations()).findByRole('button', { name: 'Edit link to Gem' }),
    )
    const dialog = await screen.findByRole('dialog', { name: 'Edit link' })
    expect(within(dialog).getByText('Crown related to Gem.')).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Role'), 'twin')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/links/l1',
        body: { role: 'twin', revision: 1 },
      })
    })
    expect(await within(group('related to')).findByText('as twin')).toBeInTheDocument()

    await userEvent.click(
      within(relations()).getByRole('button', { name: 'Remove link to Aetheria' }),
    )
    await waitFor(() => {
      expect(
        within(relations()).queryByRole('region', { name: 'forged in' }),
      ).not.toBeInTheDocument()
    })
    expect(writes.at(-1)).toMatchObject({ method: 'DELETE', path: '/links/l2' })
  })

  it('shows readers links without editing', async () => {
    vault()
    await renderApp('/v/v1/e/a1', undefined, { readOnly: true })
    await screen.findByRole('region', { name: 'Relations' })
    await within(relations()).findByRole('link', { name: 'Gem' })
    expect(within(relations()).queryByRole('button', { name: 'Add link' })).not.toBeInTheDocument()
    expect(within(relations()).queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })
})

describe('backlinks panel', () => {
  const panel = () => screen.getByRole('region', { name: 'Backlinks' })

  it('lists linking and mentioning entities, refreshed after an editor save', async () => {
    localStorage.setItem(
      'lore.shell',
      JSON.stringify({ sidebarWidth: 256, sidebarOpen: true, rightPanelOpen: true }),
    )
    vault()
    const { router } = await renderApp('/v/v1/e/a1')
    // Crown: Gem (symmetric) and Aria (wields) link here.
    await within(panel()).findByRole('link', { name: 'Aria' })
    expect(panel()).toHaveTextContent('Ariawields')
    expect(panel()).toHaveTextContent('Gemrelated to')

    await act(() =>
      router.navigate({ to: '/v/$vault/e/$entity', params: { vault: 'v1', entity: 'a2' } }),
    )
    expect(await within(panel()).findByText('Nothing links here yet.')).toBeInTheDocument()

    // Gem's body mentions Treasury.
    await act(() =>
      router.navigate({ to: '/v/$vault/e/$entity', params: { vault: 'v1', entity: 'a3' } }),
    )
    const textbox = await screen.findByRole('textbox', { name: 'Body' }, { timeout: 4000 })
    const editor = (textbox as HTMLElement & { editor: Editor }).editor
    act(() => {
      editor
        .chain()
        .focus()
        .insertContent({
          type: 'text',
          text: 'Treasury',
          marks: [{ type: 'entityLink', attrs: { entityId: 'a2' } }],
        })
        .run()
    })
    act(() => {
      editor.commands.blur()
    })
    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument()
    })
    await act(() =>
      router.navigate({ to: '/v/$vault/e/$entity', params: { vault: 'v1', entity: 'a2' } }),
    )
    await within(panel()).findByRole('link', { name: 'Gem' })
    expect(panel()).toHaveTextContent('Gemmentioned once')
  })
})
