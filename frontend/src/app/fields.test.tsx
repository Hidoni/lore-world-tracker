import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { defineModule } from '@/core/modules'
import { CAPS, FIELD, kind, row, serveVault } from '@/test/fake-vault'
import { makeRegistry, server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const OPTIONS = [
  { key: 'red', label: 'Red', color: null },
  { key: 'blue', label: 'Blue', color: null },
]

function field(key: string, type: string, extra: Record<string, unknown> = {}) {
  return {
    ...FIELD,
    key,
    label: `${key.charAt(0).toUpperCase()}${key.slice(1)}`,
    type,
    options: OPTIONS,
    ...extra,
  }
}

const RELIC = kind('relic', 'Relic', {
  capabilities: CAPS,
  fields: [
    field('title', 'text', { section: 'Basics', sort: 1 }),
    field('weight', 'integer', { section: 'Basics', sort: 2 }),
    field('price', 'decimal', { section: 'Basics', sort: 3 }),
    field('cursed', 'boolean', { section: 'Basics', sort: 4 }),
    field('hue', 'enum', { section: 'Details', sort: 5 }),
    field('tints', 'multi_enum', { section: 'Details', sort: 6 }),
    field('source', 'url', { section: 'Details', sort: 7 }),
    field('shade', 'color', { section: 'Details', sort: 8 }),
    field('size', 'measurement', { section: 'Details', sort: 9 }),
    field('lore', 'long_text', { section: 'Details', sort: 10 }),
    field('notes', 'rich_text', { section: 'Details', sort: 11 }),
    field('forged', 'time_point', { section: 'Details', sort: 12 }),
    field('rating', 'stars', { section: 'Details', sort: 13 }),
  ],
})

function vault(options: { conflicts?: number } = {}) {
  return serveVault({
    kinds: [RELIC],
    rows: [row('r1', 'relic', 'Ring', { dimension_id: null, fields: { title: 'Old', rating: 4 } })],
    ...options,
  })
}

const fieldsRegion = () => screen.getByRole('region', { name: 'Fields' })
const fieldBodies = (writes: { method: string; body: unknown }[]) =>
  writes.filter((write) => write.method === 'PATCH').map((write) => write.body)

describe('fields panel', () => {
  it('edits text, integers and decimals inline, saving on Enter', async () => {
    const writes = vault()
    const user = userEvent.setup()
    await renderApp('/v/v1/e/r1')
    const region = await screen.findByRole('region', { name: 'Fields' })
    expect(within(region).getByText('Old')).toBeInTheDocument()

    await user.click(within(region).getByRole('button', { name: 'Edit Title' }))
    const title = within(region).getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'New{Enter}')
    expect(await within(fieldsRegion()).findByText('New')).toBeInTheDocument()

    const huge = '123456789012345678901234567890'
    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Weight' }))
    await user.type(within(fieldsRegion()).getByLabelText('Weight'), '1.5{Enter}')
    expect(await within(fieldsRegion()).findByRole('alert')).toHaveTextContent(
      'Must be a whole number',
    )
    await user.clear(within(fieldsRegion()).getByLabelText('Weight'))
    await user.type(within(fieldsRegion()).getByLabelText('Weight'), `${huge}{Enter}`)
    expect(await within(fieldsRegion()).findByText(huge)).toBeInTheDocument()

    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Price' }))
    await user.type(within(fieldsRegion()).getByLabelText('Price'), '1.50{Escape}')
    expect(within(fieldsRegion()).queryByLabelText('Price')).not.toBeInTheDocument() // cancelled
    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Price' }))
    await user.type(within(fieldsRegion()).getByLabelText('Price'), '1.50{Enter}')
    await within(fieldsRegion()).findByText('1.50')

    expect(fieldBodies(writes)).toEqual([
      { fields: { title: 'New' }, revision: 1 },
      { fields: { weight: huge }, revision: 2 },
      { fields: { price: '1.50' }, revision: 3 },
    ])
  })

  it('saves choices at once: booleans, enums, multi-enums, colors', async () => {
    const writes = vault()
    const user = userEvent.setup()
    await renderApp('/v/v1/e/r1')
    const region = await screen.findByRole('region', { name: 'Fields' })
    await user.click(within(region).getByLabelText('Cursed'))
    await waitFor(() => {
      expect(fieldBodies(writes)).toHaveLength(1)
    })
    await user.selectOptions(within(fieldsRegion()).getByLabelText('Hue'), 'blue')
    await waitFor(() => {
      expect(fieldBodies(writes)).toHaveLength(2)
    })
    await user.click(within(fieldsRegion()).getByRole('checkbox', { name: 'Blue' }))
    await waitFor(() => {
      expect(fieldBodies(writes)).toHaveLength(3)
    })
    await user.click(within(fieldsRegion()).getByRole('checkbox', { name: 'Red' }))
    await waitFor(() => {
      expect(fieldBodies(writes)).toHaveLength(4)
    })
    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Shade' }))
    await user.type(within(fieldsRegion()).getByLabelText('Shade'), '#A0B1C2{Enter}')
    await waitFor(() => {
      expect(fieldBodies(writes)).toHaveLength(5)
    })
    expect(fieldBodies(writes)).toEqual([
      { fields: { cursed: true }, revision: 1 },
      { fields: { hue: 'blue' }, revision: 2 },
      { fields: { tints: ['blue'] }, revision: 3 },
      { fields: { tints: ['red', 'blue'] }, revision: 4 },
      { fields: { shade: '#a0b1c2' }, revision: 5 },
    ])
  })

  it('checks URLs and measurements, and saves long and rich text with Ctrl+Enter', async () => {
    const writes = vault()
    const user = userEvent.setup()
    await renderApp('/v/v1/e/r1')
    const region = await screen.findByRole('region', { name: 'Fields' })
    await user.click(within(region).getByRole('button', { name: 'Edit Source' }))
    await user.type(within(fieldsRegion()).getByLabelText('Source'), 'ftp://x.y{Enter}')
    expect(await within(fieldsRegion()).findByRole('alert')).toHaveTextContent(
      'Must be an http(s) URL',
    )
    await user.clear(within(fieldsRegion()).getByLabelText('Source'))
    await user.type(within(fieldsRegion()).getByLabelText('Source'), 'https://x.y/z{Enter}')
    expect(
      await within(fieldsRegion()).findByRole('link', { name: 'https://x.y/z' }),
    ).toBeInTheDocument()

    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Size' }))
    await user.type(within(fieldsRegion()).getByLabelText('Size'), '2.5')
    await user.type(within(fieldsRegion()).getByLabelText('Size unit'), ' m {Enter}')
    await within(fieldsRegion()).findByText('2.5 m')

    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Lore' }))
    await user.type(
      within(fieldsRegion()).getByLabelText('Lore'),
      'line one{Enter}line two{Control>}{Enter}{/Control}',
    )
    await within(fieldsRegion()).findByText(/line one/)

    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Edit Notes' }))
    await user.type(
      within(fieldsRegion()).getByLabelText('Notes'),
      'A note{Control>}{Enter}{/Control}',
    )
    await within(fieldsRegion()).findByText('A note')

    expect(fieldBodies(writes)).toEqual([
      { fields: { source: 'https://x.y/z' }, revision: 1 },
      { fields: { size: { value: '2.5', unit: 'm' } }, revision: 2 },
      { fields: { lore: 'line one\nline two' }, revision: 3 },
      {
        fields: {
          notes: {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'A note' }] }],
          },
        },
        revision: 4,
      },
    ])
  })

  it('shows time fields as placeholders and module renderers for module types', async () => {
    vault()
    const stars = defineModule({
      id: 'stars',
      fieldTypeRenderers: { stars: ({ value }) => <span>{'★'.repeat(Number(value))}</span> },
    })
    server.use(
      http.get('*/api/v1/vaults/v1/registry', () =>
        Response.json(makeRegistry(['stars'], [], { kinds: [RELIC] as never })),
      ),
    )
    await renderApp('/v/v1/e/r1', [stars])
    const region = await screen.findByRole('region', { name: 'Fields' })
    expect(await within(region).findByText('★★★★')).toBeInTheDocument()
    expect(within(region).queryByRole('button', { name: 'Edit Rating' })).not.toBeInTheDocument()
    expect(within(region).queryByRole('button', { name: 'Edit Forged' })).not.toBeInTheDocument()
  })

  it('sets per-field visibility, remembers collapsed sections and shows server errors', async () => {
    const writes = vault()
    const user = userEvent.setup()
    const first = await renderApp('/v/v1/e/r1')
    const region = await screen.findByRole('region', { name: 'Fields' })
    await user.selectOptions(within(region).getByLabelText('Title visibility'), 'private')
    await waitFor(() => {
      expect(fieldBodies(writes)).toEqual([{ field_visibility: { title: 'private' }, revision: 1 }])
    })
    await user.click(within(fieldsRegion()).getByRole('button', { name: 'Details' }))
    expect(within(fieldsRegion()).getByRole('button', { name: 'Details' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(within(fieldsRegion()).queryByLabelText('Hue')).not.toBeInTheDocument()
    first.unmount()

    server.use(
      http.patch('*/api/v1/vaults/v1/entities/r1', () =>
        Response.json(
          {
            status: 422,
            code: 'validation_error',
            title: 'Invalid input',
            detail: 'Bad.',
            errors: [{ path: 'body.fields.title', code: 'invalid_value', message: 'Too fancy.' }],
          },
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    await renderApp('/v/v1/e/r1')
    const again = await screen.findByRole('region', { name: 'Fields' })
    expect(within(again).queryByLabelText('Hue')).not.toBeInTheDocument() // still collapsed
    await user.click(within(again).getByRole('button', { name: 'Edit Title' }))
    await user.type(within(again).getByLabelText('Title'), '!{Enter}')
    expect(await within(again).findByRole('alert')).toHaveTextContent('Too fancy.')
  })
})

describe('revision conflicts', () => {
  it('overwrites theirs with mine', async () => {
    const writes = vault({ conflicts: 1 })
    const user = userEvent.setup()
    await renderApp('/v/v1/e/r1')
    await user.click(await screen.findByRole('button', { name: 'Edit Title' }))
    await user.type(within(fieldsRegion()).getByLabelText('Title'), '!{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Someone saved this entity first' })
    await user.click(within(dialog).getByRole('button', { name: 'Overwrite' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(await within(fieldsRegion()).findByText('Old!')).toBeInTheDocument()
    expect(fieldBodies(writes)).toEqual([
      { fields: { title: 'Old!' }, revision: 1 },
      { fields: { title: 'Old!' }, revision: 2 }, // their revision
    ])
  })

  it('reloads theirs or copies mine', async () => {
    const writes = vault({ conflicts: 1 })
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await renderApp('/v/v1/e/r1')
    await user.click(await screen.findByRole('button', { name: 'Edit Title' }))
    await user.type(within(fieldsRegion()).getByLabelText('Title'), '?{Enter}')
    const dialog = await screen.findByRole('dialog', { name: 'Someone saved this entity first' })
    await user.click(within(dialog).getByRole('button', { name: 'Copy mine' }))
    expect(writeText).toHaveBeenCalledWith('{"fields":{"title":"Old?"}}')
    await user.click(within(dialog).getByRole('button', { name: 'Reload theirs' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(fieldBodies(writes)).toHaveLength(1) // nothing overwritten
  })
})
