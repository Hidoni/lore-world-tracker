import { http, HttpResponse } from 'msw'

import { makeRegistry, makeVault, problem, server } from './msw'

export const CAPS = {
  has_body: true,
  can_be_multiversal: false,
  has_existence: true,
  can_have_worldline: false,
  is_time_bound: false,
  is_system: false,
}

export function kind(key: string, label: string, extra: Record<string, unknown> = {}) {
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

export const FIELD = {
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

export const KINDS = [
  kind('dimension', 'Dimension', { capabilities: { ...CAPS, is_system: true } }),
  kind('artifact', 'Artifact', {
    allowed_parents: ['artifact'],
    capabilities: { ...CAPS, can_be_multiversal: true },
    fields: [FIELD, { ...FIELD, key: 'origin', label: 'Origin' }],
  }),
]

export interface Row {
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
  fields: Record<string, unknown>
  field_visibility: Record<string, string>
  summary: string
  body: unknown
}

/** The entity ids a document links to (`entityLink` marks). */
function mentioned(doc: unknown): Set<string> {
  const found = new Set<string>()
  const walk = (node: unknown) => {
    if (typeof node !== 'object' || node === null) return
    const { marks, content } = node as { marks?: unknown[]; content?: unknown[] }
    for (const mark of marks ?? []) {
      const { type, attrs } = mark as { type: string; attrs?: { entityId?: string } }
      if (type === 'entityLink' && attrs?.entityId) found.add(attrs.entityId)
    }
    for (const child of content ?? []) walk(child)
  }
  walk(doc)
  return found
}

export function row(id: string, kindKey: string, name: string, extra: Partial<Row> = {}): Row {
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
    fields: {},
    field_visibility: {},
    summary: '',
    body: null,
    ...extra,
  }
}

function out(entity: Row) {
  return {
    ...entity,
    origin_timeline_id: null,
    slug: entity.name.toLowerCase(),
    body_schema_version: entity.body === null ? null : 1,
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

/** The default rows: a dimension, an artifact parent chain (Treasury → Crown → Gem). */
export function defaultRows(): Row[] {
  return [
    row('d1', 'dimension', 'Aetheria'),
    row('a2', 'artifact', 'Treasury'),
    row('a1', 'artifact', 'Crown', {
      parent_id: 'a2',
      aliases: [{ id: 'al1', alias: 'Diadem', alias_kind: 'alias', visibility: 'public' }],
    }),
    row('a3', 'artifact', 'Gem', { parent_id: 'a1' }),
  ]
}

/**
 * An in-memory vault `v1` behind MSW (entities, registry, writes, bodies with their mentions and
 * backlinks, the quick switcher); returns the write requests it saw. `conflicts` PATCHes answer `409 revision_conflict` first, as if someone saved meanwhile.
 */
export function serveVault(options: { kinds?: unknown[]; rows?: Row[]; conflicts?: number } = {}) {
  let conflicts = options.conflicts ?? 0
  const rows = new Map<string, Row>(
    (options.rows ?? defaultRows()).map((entity) => [entity.id, entity]),
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
      HttpResponse.json(makeRegistry([], [], { kinds: (options.kinds ?? KINDS) as typeof KINDS })),
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
    http.get('*/api/v1/vaults/v1/search/quick', ({ request }) => {
      const q = (new URL(request.url).searchParams.get('q') ?? '').toLowerCase()
      const items = [...rows.values()]
        .filter((entity) => entity.deleted_at === null && entity.name.toLowerCase().startsWith(q))
        .map((entity) => ({
          doc_type: 'entity',
          doc_id: entity.id,
          entity_id: entity.id,
          kind: entity.kind,
          name: entity.name,
          alias: null,
          icon: null,
          color: null,
          dimension_id: entity.dimension_id,
          visibility: entity.visibility,
        }))
      return HttpResponse.json({ items })
    }),
    http.get('*/api/v1/vaults/v1/entities/:id/backlinks', ({ params }) =>
      HttpResponse.json({
        items: [...rows.values()]
          .filter((source) => mentioned(source.body).has(String(params.id)))
          .map((source) => ({
            entity: { id: source.id, kind: source.kind, name: source.name },
            links: [],
            mentions: { public: 1, spoiler: 0, private: 0 },
          })),
      }),
    ),
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
      if (conflicts > 0 || body.revision !== entity.revision) {
        conflicts = Math.max(0, conflicts - 1)
        entity.revision += 1 // someone else saved
        return problem(409, 'revision_conflict', 'Revision conflict', 'Someone saved first.')
      }
      const merge = (current: Record<string, unknown>, patch: unknown) => {
        const next = new Map(Object.entries(current))
        for (const [key, value] of Object.entries((patch ?? {}) as Record<string, unknown>)) {
          if (value === null) next.delete(key)
          else next.set(key, value)
        }
        return Object.fromEntries(next)
      }
      entity.fields = merge(entity.fields, body.fields)
      entity.field_visibility = merge(entity.field_visibility, body.field_visibility) as Record<
        string,
        string
      >
      // Saving a body changes the backlinks of what it (no longer) mentions.
      const before = mentioned(entity.body)
      if ('body' in body) entity.body = body.body
      const after = mentioned(entity.body)
      const changed = [...before, ...after].filter((id) => before.has(id) !== after.has(id))
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
        affected: { entities: [entity.id, ...changed], ...NOTHING },
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
