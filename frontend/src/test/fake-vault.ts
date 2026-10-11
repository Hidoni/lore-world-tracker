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

export function linkType(key: string, label: string, extra: Record<string, unknown> = {}) {
  return {
    key,
    module: 'core',
    user_defined: false,
    label,
    inverse_label: null as string | null,
    description: '',
    source_kinds: '*' as string | string[],
    target_kinds: '*' as string | string[],
    symmetric: false,
    temporal: 'never',
    unique: 'none',
    max_targets_per_source: null,
    max_sources_per_target: null,
    data_schema: null,
    graph: { color: null, dashed: false, weight: 1 },
    archived: false,
    ...extra,
  }
}

export interface LinkRow {
  id: string
  link_type: string
  source_id: string
  target_id: string
  role?: string | null
  data?: Record<string, unknown>
  visibility?: 'public' | 'spoiler' | 'private'
  revision?: number
}

function linkOut(link: LinkRow) {
  return {
    role: null,
    data: {},
    visibility: 'public',
    revision: 1,
    timeline_id: null,
    valid_from: null,
    valid_to: null,
    time_status: null,
    sort_key: null,
    created_at: '2026-10-11T10:00:00.000000+00:00',
    updated_at: '2026-10-11T10:00:00.000000+00:00',
    deleted_at: null,
    ...link,
  }
}

/** A cursor page (`limit`, `cursor`: the offset as a string). */
function paged<T>(items: T[], url: URL): { items: T[]; next_cursor: string | null } {
  const limit = Number(url.searchParams.get('limit') ?? '200')
  const offset = Number(url.searchParams.get('cursor') ?? '0')
  const next = offset + limit
  return {
    items: items.slice(offset, next),
    next_cursor: next < items.length ? String(next) : null,
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
export function serveVault(
  options: {
    kinds?: unknown[]
    rows?: Row[]
    conflicts?: number
    linkTypes?: ReturnType<typeof linkType>[]
    links?: LinkRow[]
  } = {},
) {
  let conflicts = options.conflicts ?? 0
  const types = options.linkTypes ?? [linkType('core.related', 'related to', { symmetric: true })]
  const links = new Map((options.links ?? []).map((link) => [link.id, linkOut(link)]))
  let linkSeq = 0
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
  const existing = (id: string): Row => {
    const entity = rows.get(id)
    if (entity === undefined) throw new Error(`no entity ${id}`)
    return entity
  }
  const linked = (entity: Row) => ({
    id: entity.id,
    kind: entity.kind,
    name: entity.name,
    icon: null,
    color: null,
    dimension_id: entity.dimension_id,
    deleted_at: entity.deleted_at,
  })
  /** An entity's links as `GET …/links` lists them: symmetric ones once, labelled from its side. */
  const entityLinks = (id: string) =>
    [...links.values()]
      .filter((link) => link.source_id === id || link.target_id === id)
      .map((link) => {
        const type = types.find((candidate) => candidate.key === link.link_type)
        const out = link.source_id === id
        const other = existing(out ? link.target_id : link.source_id)
        return {
          link,
          direction: type?.symmetric ? 'both' : out ? 'out' : 'in',
          label:
            type?.symmetric || out
              ? (type?.label ?? link.link_type)
              : (type?.inverse_label ?? type?.label ?? link.link_type),
          other: linked(other),
        }
      })
  server.use(
    http.get('*/api/v1/vaults/v1', () => HttpResponse.json(makeVault('v1', 'Atlas'))),
    http.get('*/api/v1/vaults/v1/registry', () =>
      HttpResponse.json(makeRegistry([], [], { kinds: (options.kinds ?? KINDS) as typeof KINDS })),
    ),
    http.get('*/api/v1/vaults/v1/entities', ({ request }) => {
      const url = new URL(request.url)
      const kinds = url.searchParams.getAll('kind')
      const q = url.searchParams.get('q')?.toLowerCase()
      const dimension = url.searchParams.get('dimension')
      const sort = url.searchParams.get('sort') ?? 'name'
      const items = [...rows.values()]
        .filter((entity) => entity.deleted_at === null)
        .filter((entity) => kinds.length === 0 || kinds.includes(entity.kind))
        .filter((entity) => q === undefined || entity.name.toLowerCase().startsWith(q))
        .filter(
          (entity) =>
            dimension === null || entity.dimension_id === dimension || entity.dimension_id === null,
        )
      if (sort.endsWith('name')) items.sort((a, b) => a.name.localeCompare(b.name))
      if (sort.startsWith('-')) items.reverse()
      return HttpResponse.json(paged(items.map(out), url))
    }),
    http.get('*/api/v1/vaults/v1/tree', ({ request }) => {
      const url = new URL(request.url)
      const kinds = url.searchParams.getAll('kind')
      const parent = url.searchParams.get('parent')
      const inTree = (entity: Row | undefined): entity is Row =>
        entity?.deleted_at === null && (kinds.length === 0 || kinds.includes(entity.kind))
      const items = [...rows.values()]
        .filter(inTree)
        .filter((entity) =>
          parent === null
            ? entity.parent_id === null || !inTree(found(entity.parent_id))
            : entity.parent_id === parent,
        )
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((entity) => {
          const children = [...rows.values()].filter(
            (child) => child.parent_id === entity.id && inTree(child),
          )
          return {
            id: entity.id,
            kind: entity.kind,
            name: entity.name,
            icon: null,
            color: null,
            dimension_id: entity.dimension_id,
            parent_id: entity.parent_id,
            multiversal: entity.dimension_id === null,
            visibility: entity.visibility,
            sort_key: null,
            has_children: children.length > 0,
            child_counts: children.length > 0 ? { [entity.kind]: children.length } : {},
          }
        })
      return HttpResponse.json(paged(items, url))
    }),
    http.get('*/api/v1/vaults/v1/trash', ({ request }) => {
      const items = [...rows.values()]
        .filter((entity) => entity.deleted_at !== null)
        .map((entity) => ({
          ...out(entity),
          orphan_count: [...rows.values()].filter(
            (child) => child.parent_id === entity.id && child.deleted_at === null,
          ).length,
        }))
      return HttpResponse.json(paged(items, new URL(request.url)))
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
    http.get('*/api/v1/vaults/v1/entities/:id/links', ({ params }) =>
      HttpResponse.json({ items: entityLinks(String(params.id)) }),
    ),
    http.get('*/api/v1/vaults/v1/entities/:id/backlinks', ({ params }) => {
      const id = String(params.id)
      const incoming = entityLinks(id).filter((item) => item.direction !== 'out')
      const sources = new Set([
        ...incoming.map((item) => item.other.id),
        ...[...rows.values()].filter((row) => mentioned(row.body).has(id)).map((row) => row.id),
      ])
      return HttpResponse.json({
        items: [...sources].map((sourceId) => {
          const source = existing(sourceId)
          return {
            entity: linked(source),
            // The links as the source sees them.
            links: entityLinks(sourceId).filter((item) => item.other.id === id),
            mentions: { public: mentioned(source.body).has(id) ? 1 : 0, spoiler: 0, private: 0 },
          }
        }),
      })
    }),
    http.get('*/api/v1/vaults/v1/link-types', () => HttpResponse.json({ items: types })),
    http.post('*/api/v1/vaults/v1/links', async ({ request }) => {
      const body = (await record(request)) as unknown as LinkRow
      linkSeq += 1
      const link = linkOut({ ...body, id: `l-new${linkSeq}` })
      links.set(link.id, link)
      return HttpResponse.json(
        { link, affected: { entities: [link.source_id, link.target_id], ...NOTHING } },
        { status: 201 },
      )
    }),
    http.patch('*/api/v1/vaults/v1/links/:id', async ({ request, params }) => {
      const body = await record(request)
      const link = links.get(String(params.id))
      if (!link) return new HttpResponse(null, { status: 404 })
      const change = Object.fromEntries(Object.entries(body).filter(([key]) => key !== 'revision'))
      Object.assign(link, change, { revision: link.revision + 1 })
      return HttpResponse.json({
        link,
        affected: { entities: [link.source_id, link.target_id], ...NOTHING },
      })
    }),
    http.delete('*/api/v1/vaults/v1/links/:id', async ({ request, params }) => {
      await record(request)
      const link = links.get(String(params.id))
      if (!link) return new HttpResponse(null, { status: 404 })
      links.delete(link.id)
      return HttpResponse.json({
        link: { ...link, deleted_at: '2026-10-11T12:00:00.000000+00:00' },
        affected: { entities: [link.source_id, link.target_id], ...NOTHING },
      })
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
        ...('parent_id' in body ? { parent_id: body.parent_id as string | null } : {}),
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
