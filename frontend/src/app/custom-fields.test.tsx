import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import customFields from '@/modules/custom_fields'
import { KINDS, linkType, row, serveVault } from '@/test/fake-vault'
import { makeRegistry, problem, server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const BASE = '*/api/v1/vaults/v1/m/custom_fields'
const STAMP = '2026-10-16T10:00:00Z'
const AFFECTED = { entities: [], dimensions: [], time_changed: false, search_changed: false }
const FIELD_TYPES = ['text', 'long_text', 'integer', 'decimal', 'enum', 'multi_enum'].map(
  (key) => ({ key, label: key, description: '' }),
)

interface Write {
  method: string
  path: string
  body: unknown
  query: string
}

function customKind(key: string, label: string, extra: Record<string, unknown> = {}) {
  return {
    key: `custom.${key}`,
    label,
    plural: `${label}s`,
    icon: 'box',
    color: '#64748b',
    description: '',
    allowed_parents: [],
    capabilities: { has_existence: true, can_be_multiversal: true, can_have_worldline: false },
    default_visibility: null,
    archived: false,
    revision: 1,
    created_at: STAMP,
    updated_at: STAMP,
    entities: 0,
    ...extra,
  }
}

function customField(id: string, key: string, label: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind_key: 'artifact',
    key: `custom.${key}`,
    label,
    type: 'text',
    options: [],
    multiple: false,
    required: false,
    temporal: false,
    default_visibility: 'public',
    section: null,
    sort_key: '000001',
    help: '',
    searchable: true,
    archived: false,
    revision: 1,
    created_at: STAMP,
    updated_at: STAMP,
    entities_with_values: 0,
    ...extra,
  }
}

/** The module's endpoints over in-memory kinds and fields; returns the writes. */
function serveCustomFields(
  kinds: ReturnType<typeof customKind>[] = [],
  fields: ReturnType<typeof customField>[] = [],
) {
  const writes: Write[] = []
  const record = async (request: Request) => {
    const url = new URL(request.url)
    const text = request.method === 'DELETE' ? '' : await request.text()
    writes.push({
      method: request.method,
      path: url.pathname.replace(/^.*\/m\/custom_fields/, ''),
      body: text ? (JSON.parse(text) as unknown) : null,
      query: url.search,
    })
    return text ? (JSON.parse(text) as Record<string, unknown>) : {}
  }
  server.use(
    http.get('*/api/v1/vaults/v1/registry', () =>
      HttpResponse.json(
        makeRegistry(['custom_fields'], [], {
          kinds: KINDS,
          field_types: FIELD_TYPES,
        }),
      ),
    ),
    http.get(`${BASE}/kinds`, () => HttpResponse.json({ items: kinds })),
    http.post(`${BASE}/kinds`, async ({ request }) => {
      const body = await record(request)
      const created = customKind(String(body.key), String(body.label), body)
      created.key = `custom.${String(body.key)}`
      kinds.push(created)
      return HttpResponse.json({ kind: created, affected: AFFECTED }, { status: 201 })
    }),
    http.patch(`${BASE}/kinds/:key`, async ({ request, params }) => {
      const body = await record(request)
      const index = kinds.findIndex((kind) => kind.key === params.key)
      const current = kinds[index]
      if (current === undefined) return problem(404, 'not_found', 'Not found', 'No kind.')
      const updated = { ...current, ...body, revision: current.revision + 1 }
      kinds[index] = updated
      return HttpResponse.json({ kind: updated, affected: AFFECTED })
    }),
    http.delete(`${BASE}/kinds/:key`, async ({ request }) => {
      await record(request)
      return problem(409, 'conflict', 'Conflict', '3 entities have the kind Ship.')
    }),
    http.get(`${BASE}/fields`, () => HttpResponse.json({ items: fields })),
    http.post(`${BASE}/fields`, async ({ request }) => {
      const body = await record(request)
      const created = customField(`f${fields.length + 1}`, String(body.key), String(body.label), {
        ...body,
        key: `custom.${String(body.key)}`,
      })
      fields.push(created)
      return HttpResponse.json({ field: created, affected: AFFECTED }, { status: 201 })
    }),
    http.patch(`${BASE}/fields/:id`, async ({ request, params }) => {
      const body = await record(request)
      const index = fields.findIndex((field) => field.id === params.id)
      const current = fields[index]
      if (current === undefined) return problem(404, 'not_found', 'Not found', 'No field.')
      const updated = { ...current, ...body, revision: current.revision + 1 }
      fields[index] = updated
      return HttpResponse.json({ field: updated, affected: AFFECTED })
    }),
    http.delete(`${BASE}/fields/:id`, async ({ request, params }) => {
      await record(request)
      fields.splice(
        fields.findIndex((field) => field.id === params.id),
        1,
      )
      return HttpResponse.json({ id: params.id, affected: AFFECTED })
    }),
    http.post(`${BASE}/fields/reorder`, async ({ request }) => {
      const body = (await record(request)) as { ids: string[] }
      fields.sort((a, b) => body.ids.indexOf(a.id) - body.ids.indexOf(b.id))
      return HttpResponse.json({ items: fields })
    }),
  )
  return writes
}

async function openSettings(page: string) {
  await renderApp(`/v/v1/settings/${page}`, [customFields])
}

describe('settings → kinds', () => {
  it('creates a kind with an icon, color, parents, capabilities and default visibility', async () => {
    serveVault({ modules: ['custom_fields'] })
    const writes = serveCustomFields()
    await openSettings('kinds')
    expect(await screen.findByText('No custom kinds yet.')).toBeInTheDocument()
    expect(
      within(screen.getByRole('list', { name: 'Built-in kinds' })).getByText('Artifact'),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New kind' }))
    const dialog = await screen.findByRole('dialog', { name: 'New kind' })
    await userEvent.type(within(dialog).getByLabelText('Label'), 'Star ship')
    expect(within(dialog).getByLabelText('Key')).toHaveValue('star_ship')
    await userEvent.type(within(dialog).getByLabelText('Plural'), 'Star ships')
    await userEvent.click(within(dialog).getByRole('radio', { name: 'crown' }))
    await userEvent.click(within(dialog).getByLabelText('Artifact'))
    await userEvent.click(within(dialog).getByLabelText('Can travel (worldlines)'))
    await userEvent.selectOptions(within(dialog).getByLabelText('New entities are'), 'spoiler')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'POST',
        path: '/kinds',
        body: {
          key: 'star_ship',
          label: 'Star ship',
          plural: 'Star ships',
          icon: 'crown',
          allowed_parents: ['misc', 'artifact'],
          capabilities: { has_existence: true, can_be_multiversal: true, can_have_worldline: true },
          default_visibility: 'spoiler',
        },
      })
    })
    expect(
      await within(await screen.findByRole('list', { name: 'Custom kinds' })).findByText(
        'Star ship',
      ),
    ).toBeInTheDocument()
  })

  it('archives a kind, and explains a refused delete', async () => {
    serveVault({ modules: ['custom_fields'] })
    const writes = serveCustomFields([customKind('ship', 'Ship', { entities: 3 })])
    await openSettings('kinds')
    await userEvent.click(await screen.findByRole('button', { name: 'Archive Ship' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/kinds/custom.ship',
        body: { revision: 1, archived: true },
      })
    })
    expect(await screen.findByText('Archived')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete Ship' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('3 entities have the kind Ship.')
  })
})

describe('settings → fields', () => {
  it('adds a choice field to a kind with its options', async () => {
    serveVault({ modules: ['custom_fields'] })
    const writes = serveCustomFields()
    await openSettings('fields')
    await userEvent.selectOptions(await screen.findByLabelText('Kind'), 'artifact')
    expect(
      within(await screen.findByRole('list', { name: 'Built-in fields' })).getByText('Era'),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New field' }))
    const dialog = await screen.findByRole('dialog', { name: 'New field' })
    await userEvent.type(within(dialog).getByLabelText('Label'), 'Rarity')
    await userEvent.selectOptions(within(dialog).getByLabelText('Type'), 'enum')
    expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add option' }))
    await userEvent.type(within(dialog).getByLabelText('Option 1 label'), 'Very rare')
    expect(within(dialog).getByLabelText('Option 1 key')).toHaveValue('very_rare')
    await userEvent.click(within(dialog).getByLabelText('Changes over time (a history of values)'))
    await userEvent.selectOptions(within(dialog).getByLabelText('Default visibility'), 'spoiler')
    await userEvent.type(within(dialog).getByLabelText('Section'), 'Lore')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        path: '/fields',
        body: {
          kind_key: 'artifact',
          key: 'rarity',
          type: 'enum',
          options: [{ key: 'very_rare', label: 'Very rare' }],
          temporal: true,
          default_visibility: 'spoiler',
          section: 'Lore',
        },
      })
    })
    expect(await screen.findByRole('list', { name: 'Lore fields' })).toHaveTextContent('Rarity')
  })

  it('converts a text field to a choice, mapping each existing value', async () => {
    serveVault({
      modules: ['custom_fields'],
      rows: [
        row('a1', 'artifact', 'Sword', { fields: { 'custom.grade': 'great' } }),
        row('a2', 'artifact', 'Shield', { fields: { 'custom.grade': 'meh' } }),
      ],
    })
    const writes = serveCustomFields(
      [],
      [customField('f1', 'grade', 'Grade', { entities_with_values: 2 })],
    )
    await openSettings('fields')
    await userEvent.selectOptions(await screen.findByLabelText('Kind'), 'artifact')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Grade' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Grade' })
    // Only the safe conversions are offered.
    const types = within(within(dialog).getByLabelText('Type')).getAllByRole('option')
    expect(types.map((option) => option.textContent)).toEqual(['text', 'long_text', 'enum'])
    await userEvent.selectOptions(within(dialog).getByLabelText('Type'), 'enum')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add option' }))
    await userEvent.type(within(dialog).getByLabelText('Option 1 label'), 'Great')
    await userEvent.selectOptions(await within(dialog).findByLabelText('Option for great'), 'great')
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
    await userEvent.selectOptions(within(dialog).getByLabelText('Option for meh'), '')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/fields/f1',
        body: { revision: 1, type: 'enum', value_map: { great: 'great', meh: null } },
      })
    })
  })

  it('reorders, asks what to do with facts, and deletes a field with its values', async () => {
    serveVault({ modules: ['custom_fields'] })
    const writes = serveCustomFields(
      [],
      [
        customField('f1', 'power', 'Power', { temporal: true, entities_with_values: 2 }),
        customField('f2', 'origin', 'Origin', { sort_key: '000002' }),
      ],
    )
    await openSettings('fields')
    await userEvent.selectOptions(await screen.findByLabelText('Kind'), 'artifact')
    await userEvent.click(await screen.findByRole('button', { name: 'Move Origin up' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        path: '/fields/reorder',
        body: { kind_key: 'artifact', ids: ['f2', 'f1'] },
      })
    })
    await userEvent.click(screen.getByRole('button', { name: 'Edit Power' }))
    let dialog = await screen.findByRole('dialog', { name: 'Edit Power' })
    await userEvent.click(within(dialog).getByLabelText('Changes over time (a history of values)'))
    await userEvent.click(within(dialog).getByLabelText('Move them to the trash'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({ body: { temporal: false, facts: 'drop' } })
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Power' }))
    dialog = await screen.findByRole('dialog', { name: 'Delete Power?' })
    expect(dialog).toHaveTextContent('2 entities have values')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete with values' }))
    await waitFor(() => {
      expect(writes.at(-1)).toMatchObject({
        method: 'DELETE',
        path: '/fields/f1',
        query: '?delete_values=true',
      })
    })
  })

  it('creates a relation field as a link type from the kind', async () => {
    const vaultWrites = serveVault({ modules: ['custom_fields'] })
    serveCustomFields()
    await openSettings('fields')
    await userEvent.selectOptions(await screen.findByLabelText('Kind'), 'artifact')
    await userEvent.click(await screen.findByRole('button', { name: 'New relation field' }))
    const dialog = await screen.findByRole('dialog', { name: 'New relation field' })
    await userEvent.type(within(dialog).getByLabelText('Label'), 'Wielder')
    await userEvent.type(within(dialog).getByLabelText('Seen from the other side'), 'Wields')
    await userEvent.click(within(dialog).getByLabelText('Artifact'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => {
      expect(vaultWrites.at(-1)).toMatchObject({
        path: '/link-types',
        body: {
          label: 'Wielder',
          inverse_label: 'Wields',
          source_kinds: ['artifact'],
          target_kinds: ['artifact'],
        },
      })
    })
  })
})

describe('relation fields on entity pages', () => {
  it('show the kind’s custom link types as rows', async () => {
    serveVault({
      modules: ['custom_fields'],
      rows: [row('a1', 'artifact', 'Sword'), row('a2', 'artifact', 'Hand')],
      linkTypes: [
        linkType('custom.wielder', 'Wielder', {
          user_defined: true,
          source_kinds: ['artifact'],
          target_kinds: ['artifact'],
          revision: 1,
        }),
      ],
      links: [{ id: 'l1', link_type: 'custom.wielder', source_id: 'a1', target_id: 'a2' }],
    })
    await renderApp('/v/v1/e/a1', [customFields])
    // The entity page and its panels load first (slow on a busy runner).
    const values = await screen.findByRole('list', { name: 'Wielder' }, { timeout: 5000 })
    expect(within(values).getByRole('link', { name: 'Hand' })).toBeInTheDocument()
  })
})
