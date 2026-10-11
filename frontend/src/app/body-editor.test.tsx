import type { Editor } from '@tiptap/core'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { keys } from '@/data'
import { defaultRows, row, serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const SAVE_WAIT = { timeout: 4000 }

const link = (id: string, text: string) => ({
  type: 'text',
  text,
  marks: [{ type: 'entityLink', attrs: { entityId: id } }],
})
const paragraph = (...content: object[]) => ({ type: 'paragraph', content })
const doc = (...content: object[]) => ({ type: 'doc', content })

function vault(extra: Parameters<typeof row>[3] = {}, conflicts = 0) {
  return serveVault({
    rows: [...defaultRows(), row('w1', 'artifact', 'Writer', extra)],
    conflicts,
  })
}

/** The TipTap editor behind the "Body" textbox (ProseMirror keeps it on its DOM node). */
async function bodyEditor(): Promise<Editor> {
  const textbox = await screen.findByRole('textbox', { name: 'Body' })
  return (textbox as HTMLElement & { editor: Editor }).editor
}

function type(editor: Editor, text: string) {
  act(() => {
    editor.chain().focus('end').insertContent(text).run()
  })
}

const bodies = (writes: { method: string; body: unknown }[]) =>
  writes
    .filter((write) => write.method === 'PATCH')
    .map((write) => (write.body as { body?: unknown }).body)

describe('body editor', () => {
  it('links an entity typed after [[ and refreshes its backlinks after saving', async () => {
    const writes = vault()
    const { queryClient } = await renderApp('/v/v1/e/w1')
    const editor = await bodyEditor()
    queryClient.setQueryData(keys.backlinks('v1', 'a1', {}), { items: [] })
    type(editor, 'The [[Cro')
    const menu = await screen.findByRole('listbox', { name: 'Link to an entity' })
    await userEvent.click(await within(menu).findByRole('option', { name: /Crown/ }))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(editor.getJSON()).toEqual(
      doc(
        paragraph({ type: 'text', text: 'The ' }, link('a1', 'Crown'), { type: 'text', text: ' ' }),
      ),
    )
    await waitFor(() => {
      expect(bodies(writes)).toHaveLength(1)
    }, SAVE_WAIT)
    expect(bodies(writes)[0]).toEqual(
      doc(
        paragraph({ type: 'text', text: 'The ' }, link('a1', 'Crown'), { type: 'text', text: ' ' }),
      ),
    )
    await waitFor(() => {
      expect(screen.getByRole('status', { name: '' })).toHaveTextContent('Saved')
    })
    // The save reported Crown as affected: its backlinks are stale.
    expect(queryClient.getQueryState(keys.backlinks('v1', 'a1', {}))?.isInvalidated).toBe(true)
  })

  it('suggests entities after @ with keyboard navigation', async () => {
    vault()
    await renderApp('/v/v1/e/w1')
    const editor = await bodyEditor()
    type(editor, '@')
    expect(await screen.findByText('Type a name to link…')).toBeInTheDocument()
    type(editor, 'T')
    const menu = await screen.findByRole('listbox')
    await within(menu).findByRole('option', { name: /Treasury/ })
    const options = within(menu).getAllByRole('option')
    expect(options.map((option) => option.textContent)).toEqual([
      'TreasuryArtifact',
      'Create “T” as…New entity',
    ])
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowDown}')
    expect(within(menu).getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowUp}{Enter}')
    expect(editor.getJSON()).toEqual(
      doc(paragraph(link('a2', 'Treasury'), { type: 'text', text: ' ' })),
    )
  })

  it('creates the target from the menu, then links to it', async () => {
    const writes = vault()
    await renderApp('/v/v1/e/w1')
    const editor = await bodyEditor()
    type(editor, '[[Sword of Dawn]]')
    await userEvent.click(await screen.findByRole('option', { name: /Create “Sword of Dawn” as…/ }))
    const dialog = await screen.findByRole('dialog', { name: 'New artifact' })
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Sword of Dawn')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(editor.getJSON()).toEqual(
        doc(paragraph(link('new1', 'Sword of Dawn'), { type: 'text', text: ' ' })),
      )
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(writes.find((write) => write.method === 'POST')?.body).toMatchObject({
      kind: 'artifact',
      name: 'Sword of Dawn',
    })
  })

  it('autosaves once after a pause, and saves what is left when leaving the page', async () => {
    const writes = vault()
    const { router } = await renderApp('/v/v1/e/w1')
    const editor = await bodyEditor()
    type(editor, 'Once')
    type(editor, ' upon')
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument()
    }, SAVE_WAIT)
    expect(bodies(writes)).toEqual([doc(paragraph({ type: 'text', text: 'Once upon' }))])
    type(editor, ' a time')
    await act(() =>
      router.navigate({ to: '/v/$vault/e/$entity', params: { vault: 'v1', entity: 'a2' } }),
    )
    await waitFor(() => {
      expect(bodies(writes)).toHaveLength(2)
    })
    expect(bodies(writes)[1]).toEqual(doc(paragraph({ type: 'text', text: 'Once upon a time' })))
  })

  it('saves an emptied body as null and stops on a revision conflict', async () => {
    const writes = vault({ body: doc(paragraph({ type: 'text', text: 'Old' })) }, 1)
    await renderApp('/v/v1/e/w1')
    const editor = await bodyEditor()
    act(() => {
      editor.chain().focus().clearContent(true).run()
    })
    expect(
      await screen.findByRole('dialog', { name: 'Someone saved this entity first' }, SAVE_WAIT),
    ).toBeInTheDocument()
    expect(bodies(writes)).toEqual([null])
    expect(screen.getByText('Not saved: someone saved first')).toBeInTheDocument()
  })
})

describe('rich-text renderer', () => {
  it('renders links with their kind and missing or trashed targets as plain text', async () => {
    serveVault({
      rows: [
        ...defaultRows(),
        row('t1', 'artifact', 'Relic', { deleted_at: '2026-10-11T11:00:00.000000+00:00' }),
        row('w1', 'artifact', 'Writer', {
          body: doc(
            { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Lore' }] },
            paragraph(
              link('a1', 'the crown'),
              { type: 'text', text: ', ' },
              link('t1', 'a relic'),
              { type: 'text', text: ', ' },
              link('0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b', 'a ghost'),
              { type: 'text', text: ' and ' },
              {
                type: 'text',
                text: 'a site',
                marks: [{ type: 'bold' }, { type: 'link', attrs: { href: 'https://example.com' } }],
              },
            ),
          ),
        }),
      ],
    })
    await renderApp('/v/v1/e/w1', undefined, { readOnly: true })
    const body = await screen.findByRole('region', { name: 'Body' })
    expect(within(body).getByRole('heading', { name: 'Lore' })).toBeInTheDocument()
    const crown = await within(body).findByRole('link', { name: 'the crown' })
    expect(crown).toHaveAttribute('href', '/v/v1/e/a1')
    expect(crown.querySelector('svg')).not.toBeNull() // the kind icon
    expect(within(body).getByRole('link', { name: 'a site' })).toHaveAttribute(
      'href',
      'https://example.com',
    )
    await waitFor(() => {
      expect(within(body).getByText('a ghost')).toHaveAttribute('data-entity-link', 'missing')
    })
    expect(within(body).getByText('a relic')).toHaveAttribute('data-entity-link', 'missing')
    expect(within(body).queryByRole('textbox')).not.toBeInTheDocument()
  })
})
