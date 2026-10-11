import { Extension, type Editor } from '@tiptap/core'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { defineModule } from '@/core/modules'
import { defaultRows, row, serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const SAVE_WAIT = { timeout: 4000 }

async function bodyEditor(): Promise<Editor> {
  const textbox = await screen.findByRole('textbox', { name: 'Body' }, SAVE_WAIT)
  return (textbox as HTMLElement & { editor: Editor }).editor
}

function type(editor: Editor, text: string) {
  act(() => {
    editor.chain().focus('end').insertContent(text).run()
  })
}

const lastBody = (writes: { method: string; body: unknown }[]) =>
  (
    writes.filter((write) => write.method === 'PATCH').at(-1)?.body as
      { body?: unknown } | undefined
  )?.body

describe('slash menu and blocks', () => {
  it('wraps text in a labelled spoiler, then makes it private', async () => {
    const writes = serveVault()
    await renderApp('/v/v1/e/a1')
    const editor = await bodyEditor()
    type(editor, 'The twist /')
    const menu = await screen.findByRole('listbox', { name: 'Insert a block' })
    expect(within(menu).getAllByRole('option').length).toBeGreaterThan(10)
    type(editor, 'spo')
    expect(
      within(menu)
        .getAllByRole('option')
        .map((option) => option.textContent),
    ).toEqual(['Spoiler blockReaders unfold it'])
    await userEvent.keyboard('{Enter}')
    const label = await screen.findByLabelText('Block label')
    await userEvent.type(label, 'Book 2')
    await userEvent.selectOptions(
      screen.getByLabelText('Who sees this block'),
      'Private: authors only',
    )
    // (The editor keeps an empty paragraph after a block.)
    expect(editor.getJSON().content.slice(0, 1)).toEqual([
      {
        type: 'visibilityBlock',
        attrs: { level: 'private', label: 'Book 2' },
        content: [{ type: 'paragraph', content: [{ type: 'text', text: 'The twist ' }] }],
      },
    ])
    await waitFor(() => {
      expect(lastBody(writes)).toEqual(editor.getJSON())
    }, SAVE_WAIT)
  })

  it('adds callouts, changes their tone and removes them keeping the text', async () => {
    serveVault()
    await renderApp('/v/v1/e/a1')
    const editor = await bodyEditor()
    type(editor, 'Beware')
    await userEvent.click(screen.getByRole('button', { name: 'Callout' }))
    expect(editor.getJSON().content[0]).toMatchObject({
      type: 'callout',
      attrs: { tone: 'note' },
    })
    await userEvent.selectOptions(await screen.findByLabelText('Callout tone'), 'Warning')
    expect(editor.getJSON().content[0]).toMatchObject({ attrs: { tone: 'warning' } })
    await userEvent.click(screen.getByRole('button', { name: 'Remove callout' }))
    expect(editor.getJSON().content[0]).toEqual({
      type: 'paragraph',
      content: [{ type: 'text', text: 'Beware' }],
    })
  })

  it('lists module block types', async () => {
    serveVault({ modules: ['stamps'] })
    const stamps = defineModule({
      id: 'stamps',
      editorExtensions: [
        Extension.create({
          name: 'stampSlash',
          addOptions: () => ({
            slashItems: [
              {
                id: 'stamp',
                title: 'Royal stamp',
                run: (e: Editor) => e.chain().focus().insertContent('[seal]').run(),
              },
            ],
          }),
        }),
      ],
    })
    await renderApp('/v/v1/e/a1', [stamps])
    const editor = await bodyEditor()
    type(editor, '/roy')
    const menu = await screen.findByRole('listbox', { name: 'Insert a block' })
    await userEvent.click(within(menu).getByRole('option', { name: 'Royal stamp' }))
    expect(editor.getText()).toBe('[seal]')
  })
})

describe('Markdown paste', () => {
  function paste(editor: Editor, text: string, html = '') {
    act(() => {
      editor.commands.focus('end')
      fireEvent.paste(editor.view.dom, {
        clipboardData: {
          getData: (kind: string) =>
            kind === 'text/plain' ? text : kind === 'text/html' ? html : '',
        },
      })
    })
  }

  it('converts Markdown and links names that resolve to one entity', async () => {
    serveVault({
      rows: [
        ...defaultRows(),
        row('t1', 'artifact', 'Twin'),
        row('t2', 'artifact', 'Twin'),
        row('w1', 'artifact', 'Writer'),
      ],
    })
    await renderApp('/v/v1/e/w1')
    const editor = await bodyEditor()
    paste(editor, '## Lore\n\nThe **[[crown]]** and [[Gem|a gem]], [[Twin]], [[Nobody]].')
    await waitFor(() => {
      expect(editor.getJSON().content[0]).toMatchObject({ type: 'heading', attrs: { level: 2 } })
    })
    expect(editor.getJSON().content[1]).toEqual({
      type: 'paragraph',
      content: [
        { type: 'text', text: 'The ' },
        {
          type: 'text',
          text: 'crown',
          marks: [{ type: 'entityLink', attrs: { entityId: 'a1' } }, { type: 'bold' }],
        },
        { type: 'text', text: ' and ' },
        { type: 'text', text: 'a gem', marks: [{ type: 'entityLink', attrs: { entityId: 'a3' } }] },
        { type: 'text', text: ', Twin, Nobody.' },
      ],
    })
    expect(
      await screen.findByText('Not linked (no single match): Twin, Nobody'),
    ).toBeInTheDocument()
  })

  it('pastes one line inline, and leaves rich pastes to the editor', async () => {
    serveVault()
    await renderApp('/v/v1/e/a1')
    const editor = await bodyEditor()
    type(editor, 'Kept in ')
    paste(editor, '[[Treasury]] today')
    await waitFor(() => {
      expect(editor.getJSON().content).toEqual([
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'Kept in ' },
            {
              type: 'text',
              text: 'Treasury',
              marks: [{ type: 'entityLink', attrs: { entityId: 'a2' } }],
            },
            { type: 'text', text: ' today' },
          ],
        },
      ])
    })
    paste(editor, '**plain**', '<p><em>rich</em></p>')
    await waitFor(() => {
      expect(editor.getText()).toContain('rich')
    })
    expect(editor.getText()).not.toContain('**')
  })
})

describe('reader rendering', () => {
  it('folds spoilers and frames callouts', async () => {
    serveVault({
      rows: [
        ...defaultRows(),
        row('w1', 'artifact', 'Writer', {
          body: {
            type: 'doc',
            content: [
              {
                type: 'visibilityBlock',
                attrs: { level: 'spoiler', label: 'Book 2' },
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'The twist' }] }],
              },
              {
                type: 'callout',
                attrs: { tone: 'warning' },
                content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Careful' }] }],
              },
            ],
          },
        }),
      ],
    })
    await renderApp('/v/v1/e/w1', undefined, { readOnly: true })
    const body = await screen.findByRole('region', { name: 'Body' })
    const spoiler = within(body).getByText('Spoiler: Book 2').closest('details')
    expect(spoiler).not.toHaveAttribute('open')
    expect(within(body).getByText('Careful').closest('aside')).toHaveAttribute(
      'data-callout',
      'warning',
    )
  })
})
