import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { makeRegistry, makeVault, server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const CAPS = {
  has_body: true,
  can_be_multiversal: false,
  has_existence: true,
  can_have_worldline: false,
  is_time_bound: false,
  is_system: false,
}

function kind(key: string, label: string, extra: Record<string, unknown> = {}) {
  return {
    key,
    module: 'core',
    label,
    plural: `${label}s`,
    icon: 'gem',
    color: '#aa0000',
    description: '',
    allowed_parents: [],
    capabilities: CAPS,
    fields: [],
    ...extra,
  }
}

const FIELD = {
  key: 'era',
  label: 'Era',
  type: 'text',
  options: [],
  multiple: false,
  required: false,
  temporal: false,
  default_visibility: 'public',
  section: null,
  sort: 0,
  help: '',
  searchable: true,
  archived: false,
}

const KINDS = [
  kind('dimension', 'Dimension', { capabilities: { ...CAPS, is_system: true } }),
  kind('artifact', 'Artifact', {
    allowed_parents: ['artifact'],
    capabilities: { ...CAPS, can_be_multiversal: true },
    fields: [FIELD, { ...FIELD, key: 'origin', label: 'Origin' }],
  }),
]

interface Row {
  id: string
  kind: string
  name: string
  parent_id: string | null
  dimension_id: string | null
  revision: number
  visibility: 'public' | 'spoiler' | 'private'
  deleted_at: string | null
  aliases: { id: string; alias: string; alias_kind: string; visibility: string }[]
  tags: { id: string; name: string; color: null }[]
}

function row(id: string, kindKey: string, name: string, extra: Partial<Row> = {}): Row {
  return {
    id,
    kind: kindKey,
    name,
    parent_id: null,
    dimension_id: kindKey === 'dimension' ? null : 'd1',
    revision: 1,
    visibility: 'public',
    deleted_at: null,
    aliases: [],
    tags: [],
    ...extra,
  }
}

function out(entity: Row) {
  return {
    ...entity,
    origin_timeline_id: null,
    slug: entity.name.toLowerCase(),
    summary: '',
    body: null,
    body_schema_version: null,
    fields: {},
    field_visibility: {},
    icon: null,
    color: null,
    cover_media_id: null,
    sort_key: null,
    ext: null,
    created_at: '2026-10-11T10:00:00.000000+00:00',
    updated_at: '2026-10-11T10:00:00.000000+00:00',
  }
}

const NOTHING = { dimensions: [], time_changed: false, search_changed: true }

/** An in-memory vault behind MSW; returns the write requests it saw. */
function serveVault() {
  const rows = new Map<string, Row>(
    [
      row('d1', 'dimension', 'Aetheria'),
      row('a2', 'artifact', 'Treasury'),
      row('a1', 'artifact', 'Crown', {
        parent_id: 'a2',
        aliases: [{ id: 'al1', alias: 'Diadem', alias_kind: 'alias', visibility: 'public' }],
      }),
      row('a3', 'artifact', 'Gem', { parent_id: 'a1' }),
    ].map((entity) => [entity.id, entity]),
  )
  const writes: { method: string; path: string; body: unknown }[] = []
  const record = async (request: Request) => {
    const url = new URL(request.url)
    const text = await request.text()
    writes.push({
      method: request.method,
      path: url.pathname.replace('/api/v1/vaults/v1', '') + url.search,
      body: text ? (JSON.parse(text) as unknown) : null,
    })
    return text ? (JSON.parse(text) as Record<string, unknown>) : {}
  }
  const found = (id: unknown) => rows.get(String(id))
  server.use(
    http.get('*/api/v1/vaults/v1', () => HttpResponse.json(makeVault('v1', 'Atlas'))),
    http.get('*/api/v1/vaults/v1/registry', () =>
      HttpResponse.json(makeRegistry([], [], { kinds: KINDS })),
    ),
    http.get('*/api/v1/vaults/v1/entities', ({ request }) => {
      const url = new URL(request.url)
      const kinds = url.searchParams.getAll('kind')
      const q = url.searchParams.get('q')?.toLowerCase()
      const items = [...rows.values()]
        .filter((entity) => entity.deleted_at === null)
        .filter((entity) => kinds.length === 0 || kinds.includes(entity.kind))
        .filter((entity) => q === undefined || entity.name.toLowerCase().startsWith(q))
        .map(out)
      return HttpResponse.json({ items, next_cursor: null })
    }),
    http.get('*/api/v1/vaults/v1/entities/:id', ({ params }) => {
      const entity = found(params.id)
      return entity ? HttpResponse.json(out(entity)) : new HttpResponse(null, { status: 404 })
    }),
    http.get('*/api/v1/vaults/v1/entities/:id/children', ({ params }) =>
      HttpResponse.json({
        items: [...rows.values()].filter((entity) => entity.parent_id === params.id).map(out),
        next_cursor: null,
      }),
    ),
    http.patch('*/api/v1/vaults/v1/entities/:id', async ({ request, params }) => {
      const body = await record(request)
      const entity = found(params.id)
      if (!entity) return new HttpResponse(null, { status: 404 })
      const aliases = body.aliases as { id?: string; alias: string }[] | undefined
      const tags = body.tags as string[] | undefined
      Object.assign(entity, {
        ...(typeof body.name === 'string' ? { name: body.name } : {}),
        ...(typeof body.visibility === 'string' ? { visibility: body.visibility } : {}),
        ...(aliases
          ? {
              aliases: aliases.map((alias, i) => ({
                id: alias.id ?? `new${i}`,
                alias: alias.alias,
                alias_kind: 'alias',
                visibility: 'public',
              })),
            }
          : {}),
        ...(tags ? { tags: tags.map((name) => ({ id: name, name, color: null })) } : {}),
        revision: entity.revision + 1,
      })
      return HttpResponse.json({
        entity: out(entity),
        affected: { entities: [entity.id], ...NOTHING },
      })
    }),
    http.delete('*/api/v1/vaults/v1/entities/:id', async ({ request, params }) => {
      await record(request)
      const entity = found(params.id)
      if (!entity) return new HttpResponse(null, { status: 404 })
      const purge = new URL(request.url).searchParams.get('purge') === 'true'
      if (purge) rows.delete(entity.id)
      else entity.deleted_at = '2026-10-11T11:00:00.000000+00:00'
      return HttpResponse.json({
        id: entity.id,
        purged: purge,
        entity: purge ? null : out(entity),
        affected: { entities: [entity.id], ...NOTHING },
      })
    }),
    http.post('*/api/v1/vaults/v1/entities/:id/restore', async ({ request, params }) => {
      await record(request)
      const entity = found(params.id)
      if (!entity) return new HttpResponse(null, { status: 404 })
      entity.deleted_at = null
      return HttpResponse.json({
        entity: out(entity),
        affected: { entities: [entity.id], ...NOTHING },
      })
    }),
    http.post('*/api/v1/vaults/v1/entities', async ({ request }) => {
      const body = await record(request)
      const created = row('new1', String(body.kind), String(body.name), {
        parent_id: (body.parent_id as string | null) ?? null,
        dimension_id: (body.dimension_id as string | null) ?? null,
      })
      rows.set(created.id, created)
      return HttpResponse.json(
        { entity: out(created), affected: { entities: [created.id], ...NOTHING } },
        { status: 201 },
      )
    }),
  )
  return writes
}

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
    expect(
      within(screen.getByRole('region', { name: 'Fields' })).getByText(/2 fields/),
    ).toBeInTheDocument()
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
