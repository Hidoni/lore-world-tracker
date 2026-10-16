import type { Editor } from '@tiptap/core'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  columnChange,
  csvHeaders,
  definitionsFrom,
  tagsFrom,
} from '@/modules/languages/lexicon/fields'
import {
  defaultRows,
  kind,
  KINDS,
  lexiconOut,
  row,
  serveVault,
  type LexiconRow,
} from '@/test/fake-vault'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }

const WORDS: LexiconRow[] = [
  {
    id: 'thalass',
    language_id: 'varnish',
    headword: 'thalass',
    pronunciation: 'θaˈlas',
    part_of_speech: 'noun',
    definitions: [
      { gloss: 'the sea', examples: [{ text: 'thalass ven', translation: 'the sea is wide' }] },
    ],
    tags: ['nature'],
  },
  {
    id: 'ven',
    language_id: 'varnish',
    headword: 'ven',
    part_of_speech: 'adjective',
    definitions: [{ gloss: 'wide' }],
  },
  { id: 'kor', language_id: 'secret', headword: 'kor', definitions: [{ gloss: 'hidden' }] },
]

function world(options: { lexicon?: LexiconRow[]; body?: unknown } = {}) {
  return serveVault({
    modules: ['languages'],
    kinds: [
      ...KINDS,
      kind('language', 'Language', { module: 'languages', icon: 'languages' }),
      kind('writing_system', 'Writing system', { module: 'languages', icon: 'type' }),
    ],
    rows: [
      ...defaultRows(),
      row('varnish', 'language', 'Varnish'),
      row('w1', 'artifact', 'Glossary', { body: options.body ?? null }),
    ],
    lexicon: options.lexicon ?? WORDS,
  })
}

const paragraph = (...content: unknown[]) => ({ type: 'paragraph', content })
const text = (value: string) => ({ type: 'text', text: value })

describe('lexicon helpers', () => {
  it('turns typed cells into updates', () => {
    const entry = lexiconOut({
      id: 'e',
      language_id: 'l',
      headword: 'thalass',
      definitions: [{ gloss: 'the sea', notes: 'poetic', examples: [] }],
    })
    expect(definitionsFrom('the sea ; a lake;', entry.definitions)).toEqual([
      { gloss: 'the sea', notes: 'poetic', examples: [] },
      { gloss: 'a lake' },
    ])
    expect(tagsFrom('a, b ,a,,')).toEqual(['a', 'b'])
    expect(columnChange(entry, 'headword', ' thalass ')).toBeNull()
    expect(columnChange(entry, 'headword', '')).toBeNull()
    expect(columnChange(entry, 'romanization', 'thalas')).toEqual({
      revision: 1,
      romanization: 'thalas',
    })
    expect(columnChange(entry, 'tags', 'sea, water')).toEqual({
      revision: 1,
      tags: ['sea', 'water'],
    })
    expect(csvHeaders('﻿word,"gloss, short",""""quoted""""\r\nx,y,z')).toEqual([
      'word',
      'gloss, short',
      '"quoted"',
    ])
  })
})

describe('lexicon', () => {
  // jsdom has no layout: give the table's scroller a size so the virtualizer renders rows.
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(480)
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(960)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lists words by alphabet, edits a cell in place and adds words from the entry row', async () => {
    const writes = world()
    await renderApp('/v/v1/e/varnish')
    const table = await screen.findByRole('table', { name: 'Lexicon' }, WAIT)
    await within(table).findByText('thalass', {}, WAIT)
    const rows = within(table).getAllByTestId('lexicon-row')
    expect(rows.map((item) => item.textContent)).toEqual([
      'thalass—θaˈlasnounthe seanature',
      'ven——adjectivewide—',
    ])

    // Click a cell, type, Enter: only that member is sent, with the revision.
    await userEvent.click(within(table).getByRole('button', { name: 'Edit glosses of ven' }))
    const cell = within(table).getByRole('textbox', { name: 'Glosses of ven' })
    await userEvent.clear(cell)
    await userEvent.type(cell, 'wide; broad{Enter}')
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/m/languages/lexicon/ven',
        body: { revision: 1, definitions: [{ gloss: 'wide' }, { gloss: 'broad' }] },
      })
    })
    expect(await within(table).findByText('wide; broad', {}, WAIT)).toBeVisible()

    // Escape cancels without saving.
    const count = writes.length
    await userEvent.click(within(table).getByRole('button', { name: 'Edit headword of ven' }))
    await userEvent.type(
      within(table).getByRole('textbox', { name: 'Headword of ven' }),
      'x{Escape}',
    )
    expect(writes).toHaveLength(count)

    // The entry row: type, Tab through, Enter adds and starts the next word.
    const headword = within(table).getByRole('textbox', { name: 'New entry: headword' })
    await userEvent.type(headword, 'aster')
    await userEvent.type(
      within(table).getByRole('textbox', { name: 'New entry: gloss' }),
      'star{Enter}',
    )
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        path: '/m/languages/varnish/lexicon',
        body: { headword: 'aster', definitions: [{ gloss: 'star' }], romanization: null },
      })
    })
    await waitFor(() => {
      expect(headword).toHaveValue('')
    })
    expect(headword).toHaveFocus()
    expect(await within(table).findByText('aster', {}, WAIT)).toBeVisible()
  }, 15_000)

  it('filters by search and part of speech', async () => {
    world()
    await renderApp('/v/v1/m/languages/varnish/lexicon')
    expect(await screen.findByRole('heading', { name: 'Lexicon of Varnish' }, WAIT)).toBeVisible()
    const table = screen.getByRole('table', { name: 'Lexicon' })
    await within(table).findByText('thalass', {}, WAIT)
    await userEvent.selectOptions(screen.getByLabelText('Part of speech'), 'adjective')
    await waitFor(() => {
      expect(within(table).queryByText('thalass')).toBeNull()
    })
    expect(within(table).getByText('ven')).toBeVisible()
    await userEvent.selectOptions(screen.getByLabelText('Part of speech'), '')
    await userEvent.type(screen.getByLabelText('Find'), 'sea')
    await waitFor(() => {
      expect(within(table).queryByText('ven')).toBeNull()
    })
    expect(screen.getByRole('link', { name: /Export CSV/ })).toHaveAttribute(
      'href',
      '/api/v1/vaults/v1/m/languages/varnish/lexicon/export',
    )
  })

  it('renders 10,000 words a window at a time', async () => {
    const many = Array.from({ length: 10_000 }, (_, index) => ({
      id: `e${index}`,
      language_id: 'varnish',
      headword: `word${String(index).padStart(5, '0')}`,
      definitions: [{ gloss: `gloss ${index}` }],
    }))
    world({ lexicon: many })
    await renderApp('/v/v1/m/languages/varnish/lexicon')
    const table = await screen.findByRole('table', { name: 'Lexicon' }, WAIT)
    await within(table).findByText('word00000', {}, WAIT)
    // Pages of 200 arrive as the table nears their end; only a window of rows is in the DOM.
    expect(within(table).getAllByTestId('lexicon-row').length).toBeLessThan(80)
    expect(Number(table.getAttribute('aria-rowcount'))).toBeGreaterThan(200)
    const scroller = within(table).getByTestId('lexicon-scroller')
    act(() => {
      scroller.scrollTop = 36 * 300
      fireEvent.scroll(scroller)
    })
    expect(await within(table).findByText('word00300', {}, WAIT)).toBeInTheDocument()
    expect(within(table).queryByText('word00000')).toBeNull()
    expect(within(table).getAllByTestId('lexicon-row').length).toBeLessThan(80)
  })

  it('opens an entry in the drawer and saves its definitions and examples', async () => {
    const writes = world()
    await renderApp('/v/v1/e/varnish')
    const table = await screen.findByRole('table', { name: 'Lexicon' }, WAIT)
    await userEvent.click(
      await within(table).findByRole('button', { name: 'Details of thalass' }, WAIT),
    )
    const drawer = await screen.findByRole('dialog', { name: 'thalass' }, WAIT)
    expect(within(drawer).getByRole('textbox', { name: 'Example 1 of definition 1' })).toHaveValue(
      'thalass ven',
    )
    await userEvent.click(within(drawer).getByRole('button', { name: 'Definition' }))
    await userEvent.type(within(drawer).getByRole('textbox', { name: 'Gloss 2' }), 'the deep')
    await userEvent.type(within(drawer).getByLabelText('Tags'), ', water')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/m/languages/lexicon/thalass',
        body: {
          revision: 1,
          definitions: [
            {
              gloss: 'the sea',
              examples: [{ text: 'thalass ven', translation: 'the sea is wide' }],
            },
            { gloss: 'the deep', examples: [] },
          ],
          tags: ['nature', 'water'],
        },
      })
    })
    const body = writes.at(-1)?.body as Record<string, unknown>
    expect(Object.keys(body).sort()).toEqual(['definitions', 'revision', 'tags'])
  }, 15_000)

  it('inserts IPA characters at the caret', async () => {
    world()
    await renderApp('/v/v1/e/varnish')
    const table = await screen.findByRole('table', { name: 'Lexicon' }, WAIT)
    const input = await within(table).findByRole(
      'textbox',
      { name: 'New entry: pronunciation' },
      WAIT,
    )
    await userEvent.type(input, 'tlas')
    ;(input as HTMLInputElement).setSelectionRange(1, 1)
    await userEvent.click(within(table).getByRole('button', { name: 'IPA characters' }))
    const palette = await screen.findByRole('group', { name: 'IPA palette' })
    await userEvent.click(within(palette).getByRole('button', { name: 'ə' }))
    expect(input).toHaveValue('təlas')
  })

  it('imports a CSV: mapping, a dry run with problems, then all rows', async () => {
    const writes = world()
    await renderApp('/v/v1/e/varnish')
    await userEvent.click(await screen.findByRole('button', { name: /Import CSV/ }, WAIT))
    const dialog = await screen.findByRole('dialog', { name: 'Import words from CSV' })
    const paste = within(dialog).getByLabelText('Or paste it')
    await userEvent.type(paste, 'Word,Meaning\naster,star\n,orphan')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Next' }))
    // "Word" names no field: map it, and the glosses.
    await userEvent.selectOptions(within(dialog).getByLabelText('Field of column Word'), 'headword')
    await userEvent.selectOptions(
      within(dialog).getByLabelText('Field of column Meaning'),
      'definitions',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check' }))
    expect(await within(dialog).findByText(/1 problem in 2 rows/, {}, WAIT)).toBeVisible()
    expect(within(dialog).getByRole('list', { name: 'Problems' })).toHaveTextContent(
      'Row 2: A headword is required.',
    )
    expect(within(dialog).getByRole('button', { name: /^Import/ })).toBeDisabled()
    expect(writes.at(-1)).toMatchObject({
      path: '/m/languages/varnish/lexicon/import?dry_run=true',
      body: { columns: { Word: 'headword', Meaning: 'definitions' } },
    })

    // Back to the file, fix it, check again, import.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Back' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Back' }))
    await userEvent.clear(within(dialog).getByLabelText('Or paste it'))
    await userEvent.type(
      within(dialog).getByLabelText('Or paste it'),
      'headword,definitions\naster,star\nnox,night',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Next' }))
    expect(within(dialog).getByLabelText('Field of column headword')).toHaveValue('headword')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check' }))
    expect(await within(dialog).findByText('2 rows are ready to import.', {}, WAIT)).toBeVisible()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import 2 entries' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Import words from CSV' })).toBeNull()
    })
    expect(writes.at(-1)?.path).toBe('/m/languages/varnish/lexicon/import?dry_run=false')
    const table = screen.getByRole('table', { name: 'Lexicon' })
    expect(await within(table).findByText('nox', {}, WAIT)).toBeVisible()
  }, 15_000)
})

describe('lexiconRef', () => {
  it('shows the headword with its glosses, or "a word" when it can’t be seen', async () => {
    world({
      body: {
        type: 'doc',
        content: [
          paragraph(
            text('The word '),
            { type: 'lexiconRef', attrs: { entryId: 'thalass', languageId: 'varnish' } },
            text(' and '),
            { type: 'lexiconRef', attrs: { entryId: 'gone', languageId: 'varnish' } },
          ),
        ],
      },
    })
    await renderApp('/v/v1/e/w1', undefined, { readOnly: true })
    const body = await screen.findByRole('region', { name: 'Body' })
    const word = await within(body).findByRole('button', { name: 'thalass' }, WAIT)
    await userEvent.hover(word)
    expect(await screen.findByRole('tooltip', {}, WAIT)).toHaveTextContent(
      '/θaˈlas/ · noun · the sea',
    )
    expect(await within(body).findByText('a word', {}, WAIT)).toBeVisible()
  })

  it('inserts a word with @@ or the slash menu', async () => {
    world()
    await renderApp('/v/v1/e/w1')
    const textbox = await screen.findByRole('textbox', { name: 'Body' }, WAIT)
    const editor = (textbox as HTMLElement & { editor: Editor }).editor
    act(() => {
      editor.chain().focus('end').insertContent('Say @@sea').run()
    })
    const menu = await screen.findByRole('listbox', { name: 'Insert a word' }, WAIT)
    expect(await within(menu).findByRole('option', { name: /thalass/ }, WAIT)).toHaveTextContent(
      'the sea',
    )
    // The core `@` menu stays closed.
    expect(screen.queryByRole('listbox', { name: 'Link to an entity' })).toBeNull()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => {
      expect(screen.queryByRole('listbox', { name: 'Insert a word' })).toBeNull()
    })
    expect(editor.getJSON().content[0]).toMatchObject({
      type: 'paragraph',
      content: [
        { type: 'text', text: 'Say ' },
        { type: 'lexiconRef', attrs: { entryId: 'thalass', languageId: 'varnish' } },
        { type: 'text', text: ' ' },
      ],
    })
    expect(await within(textbox).findByRole('button', { name: 'thalass' }, WAIT)).toBeVisible()

    // The slash menu's "Word" opens the same menu.
    act(() => {
      editor.chain().focus('end').insertContent('/wor').run()
    })
    const blocks = await screen.findByRole('listbox', { name: 'Insert a block' })
    await userEvent.click(within(blocks).getByRole('option', { name: /^Word/ }))
    expect(await screen.findByRole('listbox', { name: 'Insert a word' }, WAIT)).toHaveTextContent(
      'Type a word or a gloss…',
    )
  })

  it('renders lexicon hits in search results', async () => {
    world()
    await renderApp('/v/v1/search?q=wide')
    const results = await screen.findByRole('list', { name: 'Results' }, WAIT)
    const link = await within(results).findByRole('link', { name: 'ven' }, WAIT)
    expect(link).toHaveAttribute('href', '/v/v1/m/languages/varnish/lexicon')
    expect(await within(results).findByText(/Word · Varnish/, {}, WAIT)).toBeVisible()
  })
})

describe('lexicon pages in reader mode', () => {
  it.each(['/v/v1/e/varnish', '/v/v1/m/languages/varnish/lexicon'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
    },
  )
})
