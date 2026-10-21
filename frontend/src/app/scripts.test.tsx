import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { scaleOf } from '@/modules/scripts/fonts'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import {
  defaultRows,
  FIELD,
  kind,
  KINDS,
  linkType,
  row,
  serveVault,
  type LexiconRow,
} from '@/test/fake-vault'
import { server } from '@/test/msw'
import { settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const WAIT = { timeout: 5000 }

const field = (key: string, label: string, type: string, extra: Record<string, unknown> = {}) => ({
  ...FIELD,
  key,
  label,
  type,
  section: 'Script font',
  ...extra,
})

const LANGUAGE = kind('language', 'Language', {
  module: 'languages',
  icon: 'languages',
  fields: [
    field('scripts.headwords', 'Headwords', 'enum', {
      options: [
        { key: 'script', label: "In the script's font", color: null },
        { key: 'plain', label: 'Plain text', color: null },
      ],
    }),
  ],
})
const WRITING_SYSTEM = kind('writing_system', 'Writing system', {
  module: 'languages',
  icon: 'type',
  fields: [
    { ...FIELD, key: 'direction', label: 'Direction', type: 'text' },
    field('scripts.font', 'Font', 'media'),
    field('scripts.font_scale', 'Font size', 'integer'),
    field('scripts.sample', 'Sample', 'long_text'),
  ],
})

const WORDS: LexiconRow[] = [
  { id: 'thalass', language_id: 'varnish', headword: 'thalass', definitions: [{ gloss: 'sea' }] },
  { id: 'aelin', language_id: 'elvish', headword: 'aelin', definitions: [{ gloss: 'lake' }] },
]

const fontItem = (id: string, filename: string, mime = 'font/woff2') => ({
  id,
  sha256: `${id}0000000000000000`,
  filename,
  mime,
  size: 2048,
  width: null,
  height: null,
  alt: '',
  caption: '',
  revision: 1,
  created_at: '2026-10-01T00:00:00Z',
  deleted_at: null,
  refs: [],
})

/** Varnish and Elvish are written in Runes (a font, rtl, 150 %); Elvish shows plain headwords. */
function world() {
  const fonts = [fontItem('f1', 'runes.woff2'), fontItem('f2', 'runes-bold.ttf', 'font/ttf')]
  const queries: Record<string, string>[] = []
  const writes = serveVault({
    modules: ['languages', 'media', 'scripts'],
    kinds: [...KINDS, LANGUAGE, WRITING_SYSTEM],
    linkTypes: [linkType('languages.uses_script', 'written in', { inverse_label: 'used by' })],
    rows: [
      ...defaultRows(),
      row('varnish', 'language', 'Varnish'),
      row('elvish', 'language', 'Elvish', { fields: { 'scripts.headwords': 'plain' } }),
      row('runes', 'writing_system', 'Runes', {
        fields: {
          direction: 'rtl',
          'scripts.font': 'f1',
          'scripts.font_scale': '150',
          'scripts.sample': 'ᚠᚢᚦ',
        },
      }),
    ],
    links: [
      { id: 'l1', link_type: 'languages.uses_script', source_id: 'varnish', target_id: 'runes' },
      { id: 'l2', link_type: 'languages.uses_script', source_id: 'elvish', target_id: 'runes' },
    ],
    lexicon: WORDS,
  })
  server.use(
    http.get('*/api/v1/vaults/v1/m/media/items', ({ request }) => {
      const query = Object.fromEntries(new URL(request.url).searchParams)
      queries.push(query)
      return HttpResponse.json({
        items: fonts.filter((item) => item.mime.startsWith(query.mime ?? '')),
        next_cursor: null,
      })
    }),
    http.get('*/api/v1/vaults/v1/m/media/items/:id', ({ params }) => {
      const item = fonts.find((font) => font.id === params.id)
      return item === undefined ? new HttpResponse(null, { status: 404 }) : HttpResponse.json(item)
    }),
  )
  return { writes, queries }
}

const fontRules = () =>
  [...document.head.querySelectorAll('style[data-lore-script-font]')].map(
    (style) => style.textContent,
  )

describe('script fonts', () => {
  beforeEach(() => {
    localStorage.clear()
    // jsdom has no layout: give the lexicon's scroller a size so the virtualizer renders rows.
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(480)
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(960)
    vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(480)
    vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(960)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('clamps font sizes', () => {
    expect([scaleOf('150'), scaleOf(10), scaleOf(1000), scaleOf(null), scaleOf('x')]).toEqual([
      150, 50, 400, 100, 100,
    ])
  })

  it("shows a language's headwords in its script's font", async () => {
    world()
    await renderApp('/v/v1/e/varnish')
    const table = await screen.findByRole('table', { name: 'Lexicon' }, WAIT)
    await waitFor(() => {
      const word = within(table).getByText('thalass')
      expect(word).toHaveAttribute('data-script-font', 'runes')
      expect(word).toHaveAttribute('dir', 'rtl')
      expect(word.style.fontFamily).toContain('lore-script-f1')
      expect(word.style.fontSize).toBe('150%')
    }, WAIT)
    expect(fontRules()).toContainEqual(
      expect.stringMatching(
        /@font-face \{ font-family: "lore-script-f1"; src: url\(".*\/m\/media\/items\/f1\/file\?size=original"\); font-display: swap; \}/,
      ),
    )
  })

  it('leaves headwords plain where the language says so', async () => {
    world()
    await renderApp('/v/v1/e/elvish')
    const table = await screen.findByRole('table', { name: 'Lexicon' }, WAIT)
    const word = await within(table).findByText('aelin', {}, WAIT)
    await settled()
    expect(word).not.toHaveAttribute('data-script-font')
  })

  it("shows a writing system's sample in its font and picks its font from the library's fonts", async () => {
    const { writes, queries } = world()
    await renderApp('/v/v1/e/runes')
    const panel = await screen.findByRole('region', { name: 'Script sample' }, WAIT)
    const sample = within(panel).getByText('ᚠᚢᚦ')
    expect(sample.style.fontFamily).toContain('lore-script-f1')
    expect(sample).toHaveAttribute('dir', 'rtl')
    expect(await screen.findByText('runes.woff2', {}, WAIT)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Edit Font' }))
    await userEvent.click(screen.getByRole('button', { name: 'Replace the font' }))
    const picker = await screen.findByRole('dialog', { name: 'Font' })
    await userEvent.click(
      await within(picker).findByRole('button', { name: 'Pick runes-bold.ttf' }, WAIT),
    )
    expect(queries).toContainEqual(expect.objectContaining({ mime: 'font/' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        body: { fields: { 'scripts.font': 'f2' } },
      })
    })
  })

  it(
    'is accessible',
    async () => {
      world()
      await renderApp('/v/v1/e/runes')
      await screen.findByRole('region', { name: 'Script sample' }, WAIT)
      await settled()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})
