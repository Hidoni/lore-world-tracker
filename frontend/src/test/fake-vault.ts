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
  /** Kind-specific data (dimensions, calendars, …); wire format. */
  ext?: unknown
}

/** A document's text (paragraphs joined by spaces). */
function bodyText(doc: unknown): string {
  if (typeof doc !== 'object' || doc === null) return ''
  const { text, content } = doc as { text?: string; content?: unknown[] }
  return text ?? (content ?? []).map(bodyText).join(' ').replace(/\s+/g, ' ').trim()
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
    ext: entity.ext ?? null,
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
    revision: null as number | null,
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

export interface ModuleStateRow {
  id: string
  name: string
  description: string
  depends_on: string[]
  default_enabled: boolean
  enabled: boolean
}

export interface BackupRow {
  id: string
  kind: string
  reason: string | null
  created_at: string
  size: number
  includes_media: boolean
  app_version: string
  schema_revision: string | null
}

/** A recorded changeset (data-model.md §7) with what its undo answers. */
export interface FakeChangeset {
  id: string
  summary: string
  origin?: string
  entities: { id: string; name: string | null; kind: string | null; exists: boolean }[]
  changes: {
    table_name: string
    row_id: string
    op: 'insert' | 'update' | 'delete'
    before: Record<string, unknown> | null
    after: Record<string, unknown> | null
    entity_ids: string[]
  }[]
  reverted_by_changeset_id?: string | null
  reverts_changeset_id?: string | null
  /** The undo answers `409 revert_conflict` with this context. */
  conflict?: { rows?: unknown[]; problems?: { message: string }[] }
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

/** A consistency finding (wire format); open unless `suppression` is set. */
export function finding(
  fingerprint: string,
  rule_id: string,
  severity: 'error' | 'warning' | 'info',
  message: string,
  subjects: { id: string; name: string | null; kind: string | null }[],
  extra: Record<string, unknown> = {},
) {
  return {
    fingerprint,
    rule_id,
    owner: rule_id.split('.')[0] ?? 'core',
    title: rule_id,
    severity,
    certainty: 'definite' as 'definite' | 'possible',
    message,
    subjects,
    timeline_id: null as string | null,
    data: {},
    suppression: null as { note: string; created_at: string } | null,
    created_at: '2026-10-11T10:00:00.000000+00:00',
    updated_at: '2026-10-11T10:00:00.000000+00:00',
    ...extra,
  }
}

/** A consistency rule (`RuleInfo`). */
export function rule(id: string, title: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    owner: id.split('.')[0] ?? 'core',
    title,
    description: `${title}: the description.`,
    category: 'structure',
    default_severity: 'error' as 'off' | 'warning' | 'error',
    severity: 'error' as 'off' | 'warning' | 'error',
    configurable: true,
    findings: 0,
    ...extra,
  }
}

/** A finding that blocks a write (`422 consistency_error` `context.findings`). */
/** A lexicon entry of the languages module (`LexiconEntryOut` in the fake's terms). */
export interface LexiconRow {
  id: string
  language_id: string
  headword: string
  romanization?: string | null
  pronunciation?: string | null
  part_of_speech?: string | null
  definitions?: {
    gloss: string
    notes?: string | null
    examples?: { text: string; translation?: string | null }[]
  }[]
  tags?: string[]
  visibility?: 'public' | 'spoiler' | 'private'
}

/** The wire form of a lexicon entry. */
export function lexiconOut(entry: LexiconRow & { revision?: number }) {
  return {
    romanization: null,
    pronunciation: null,
    part_of_speech: null,
    definitions: [],
    etymology: { text: null, sources: [] },
    notes: null,
    tags: [] as string[],
    visibility: 'public' as 'public' | 'spoiler' | 'private',
    timeline_id: null,
    valid_from: null,
    valid_to: null,
    valid_from_t: null,
    valid_to_t: null,
    time_status: null,
    sort_key: null,
    revision: 1,
    collation_key: entry.headword,
    created_at: '2026-10-11T10:00:00.000000+00:00',
    updated_at: '2026-10-11T10:00:00.000000+00:00',
    deleted_at: null as string | null,
    ...entry,
  }
}

export interface BlockingRow {
  fingerprint: string
  rule_id: string
  message: string
  subjects: string[]
  suppressible: boolean
}

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
    /** Enabled modules besides core (their frontend definitions are passed to `renderApp`). */
    modules?: string[]
    /** History, newest first. */
    changesets?: FakeChangeset[]
    /** Module states (`depends_on`, `enabled`) instead of `modules`' defaults. */
    moduleStates?: ModuleStateRow[]
    backups?: BackupRow[]
    /** The first restores answer `422 invalid_backup`. */
    restoreFailures?: number
    findings?: ReturnType<typeof finding>[]
    rules?: ReturnType<typeof rule>[]
    /** Entity writes (create, update) without `suppress` answer `422 consistency_error` with
     * these findings, `times` times (default: always). */
    refusals?: { findings: BlockingRow[]; times?: number }
    /** Lexicon entries (the languages module). */
    lexicon?: LexiconRow[]
  } = {},
) {
  let conflicts = options.conflicts ?? 0
  const types = [
    ...(options.linkTypes ?? [linkType('core.related', 'related to', { symmetric: true })]),
  ]
  const links = new Map((options.links ?? []).map((link) => [link.id, linkOut(link)]))
  let linkSeq = 0
  const moduleStates = options.moduleStates?.map((state) => ({ ...state }))
  let settings = {
    defaults: { visibility: 'public' },
    backups: { every_hours: 24, keep: 7, include_media: true },
  }
  const backups = [...(options.backups ?? [])]
  let restoreFailures = options.restoreFailures ?? 0
  const findings = [...(options.findings ?? [])]
  const rules = [...(options.rules ?? [])]
  let refusals = options.refusals?.times ?? Number.POSITIVE_INFINITY
  /** `422 consistency_error` for a write that doesn't suppress the configured findings. */
  const refuse = (body: Record<string, unknown>) => {
    if (options.refusals === undefined || refusals <= 0 || body.suppress !== undefined) return null
    refusals -= 1
    const blocking = options.refusals.findings
    return HttpResponse.json(
      {
        type: 'about:blank',
        status: 422,
        code: 'consistency_error',
        title: 'Consistency rule violated',
        detail: 'The change breaks consistency rules.',
        errors: blocking.map((item) => ({
          path: 'suppress',
          code: item.rule_id,
          message: item.message,
        })),
        context: { findings: blocking.map((item) => ({ ...item, certainty: 'definite' })) },
      },
      { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
    )
  }
  const lexicon = new Map((options.lexicon ?? []).map((entry) => [entry.id, lexiconOut(entry)]))
  let lexiconSeq = 0
  const lexiconWrite = (entry: ReturnType<typeof lexiconOut>) => ({
    entry,
    affected: { entities: [entry.language_id], ...NOTHING },
  })
  const changesets = [...(options.changesets ?? [])]
  const summary = (changeset: FakeChangeset) => ({
    id: changeset.id,
    created_at: '2026-10-11T10:00:00.000000+00:00',
    updated_at: '2026-10-11T10:00:00.000000+00:00',
    origin: changeset.origin ?? 'ui',
    summary: changeset.summary,
    reverts_changeset_id: changeset.reverts_changeset_id ?? null,
    reverted_by_changeset_id: changeset.reverted_by_changeset_id ?? null,
    change_count: changeset.changes.length,
    entities: changeset.entities,
  })
  const detail = (changeset: FakeChangeset) => ({
    ...summary(changeset),
    changes: changeset.changes.map((change, index) => ({ id: index + 1, ...change })),
  })
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
      HttpResponse.json({
        ...makeRegistry(options.modules ?? [], [], {
          kinds: (options.kinds ?? KINDS) as typeof KINDS,
        }),
        ...(moduleStates ? { modules: moduleStates } : {}),
      }),
    ),
    http.get('*/api/v1/vaults/v1/consistency/findings', ({ request }) => {
      const url = new URL(request.url)
      const status = url.searchParams.get('status') ?? 'open'
      const severities = url.searchParams.getAll('severity')
      const certainty = url.searchParams.get('certainty')
      const ruleIds = url.searchParams.getAll('rule')
      const owner = url.searchParams.get('owner')
      const entity = url.searchParams.get('entity')
      const timeline = url.searchParams.get('timeline')
      const rank = { error: 0, warning: 1, info: 2 }
      const items = findings
        .filter((item) =>
          status === 'all' ? true : status === 'open' ? !item.suppression : !!item.suppression,
        )
        .filter((item) => severities.length === 0 || severities.includes(item.severity))
        .filter((item) => certainty === null || item.certainty === certainty)
        .filter((item) => ruleIds.length === 0 || ruleIds.includes(item.rule_id))
        .filter((item) => owner === null || item.owner === owner)
        .filter((item) => entity === null || item.subjects.some((subject) => subject.id === entity))
        .filter((item) => timeline === null || item.timeline_id === timeline)
        .sort((a, b) => rank[a.severity] - rank[b.severity])
      return HttpResponse.json(paged(items, url))
    }),
    http.get('*/api/v1/vaults/v1/consistency/rules', () => HttpResponse.json({ items: rules })),
    http.get('*/api/v1/vaults/v1/tags', () => {
      const counts = new Map<string, { id: string; name: string; color: null; count: number }>()
      for (const entity of rows.values()) {
        if (entity.deleted_at !== null) continue
        for (const tag of (entity as { tags?: { id: string; name: string }[] }).tags ?? []) {
          const known = counts.get(tag.id)
          if (known === undefined) counts.set(tag.id, { ...tag, color: null, count: 1 })
          else known.count += 1
        }
      }
      return HttpResponse.json({
        items: [...counts.values()].sort((a, b) => a.name.localeCompare(b.name)),
      })
    }),
    http.get('*/api/v1/vaults/v1/timelines/:id/event-tree', () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get('*/api/v1/vaults/v1/timelines/:id/causality', ({ request }) => {
      const event = new URL(request.url).searchParams.get('event') ?? ''
      const focus = rows.get(event)
      if (focus === undefined) return problem(404, 'not_found', 'Not found', 'No such event.')
      return HttpResponse.json({
        focus: event,
        nodes: [
          {
            id: event,
            name: focus.name,
            visibility: 'public',
            start_t: null,
            end_t: null,
            time_status: null,
            importance: 3,
            category: null,
            display: { calendar_id: 'absolute', start: null, end: null },
            distance: 0,
          },
        ],
        edges: [],
        truncated: false,
      })
    }),
    http.get('*/api/v1/vaults/v1/timelines/:id/window', () =>
      HttpResponse.json({ items: [], buckets: [], series_bands: [], total: 0, culled: 0 }),
    ),
    http.get('*/api/v1/vaults/v1/dimensions/:id/timelines', ({ params }) =>
      HttpResponse.json({ dimension_id: params.id, items: [] }),
    ),
    http.patch('*/api/v1/vaults/v1/consistency/rules/:id', async ({ request, params }) => {
      const body = await record(request)
      const target = rules.find((item) => item.id === params.id)
      if (!target) return problem(404, 'not_found', 'Not found', 'No such rule.')
      const severity = body.severity as 'off' | 'warning' | 'error' | null
      target.severity = severity ?? target.default_severity
      return HttpResponse.json(target)
    }),
    http.post('*/api/v1/vaults/v1/consistency/suppressions', async ({ request }) => {
      const body = await record(request)
      const target = findings.find((item) => item.fingerprint === body.fingerprint)
      if (!target) return problem(404, 'not_found', 'Not found', 'No such finding.')
      target.suppression = { note: String(body.note), created_at: '2026-10-11T11:00:00Z' }
      return HttpResponse.json(target, { status: 201 })
    }),
    http.delete(
      '*/api/v1/vaults/v1/consistency/suppressions/:fingerprint',
      async ({ request, params }) => {
        await record(request)
        const target = findings.find((item) => item.fingerprint === params.fingerprint)
        if (!target) return problem(404, 'not_found', 'Not found', 'No such finding.')
        target.suppression = null
        return new HttpResponse(null, { status: 204 })
      },
    ),
    http.post('*/api/v1/vaults/v1/consistency/scan', async ({ request }) => {
      await record(request)
      return HttpResponse.json({ rules: rules.length, findings: findings.length })
    }),
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
      const groupBy = url.searchParams.get('group_by')
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
            group:
              groupBy !== null && typeof entity.fields[groupBy] === 'string'
                ? entity.fields[groupBy]
                : null,
          }
        })
      return HttpResponse.json(paged(items, url))
    }),
    // The species module's reads (docs/modules/species.md).
    http.get('*/api/v1/vaults/v1/m/species/:id/members', ({ params }) =>
      HttpResponse.json({
        items: entityLinks(String(params.id)).filter(
          (item) => item.link.link_type === 'species.is_a' && item.direction === 'in',
        ),
      }),
    ),
    http.get('*/api/v1/vaults/v1/m/species/descent-tree', () => {
      const found = [...rows.values()]
        .filter((entity) => entity.kind === 'species' && entity.deleted_at === null)
        .sort((a, b) => a.name.localeCompare(b.name))
      const ids = new Set(found.map((species) => species.id))
      const shown = (id: string | null): id is string => id !== null && ids.has(id)
      return HttpResponse.json({
        nodes: found.map((species) => ({
          id: species.id,
          name: species.name,
          visibility: species.visibility,
          dimension_id: species.dimension_id,
          parent_id: shown(species.parent_id) ? species.parent_id : null,
        })),
        edges: [
          ...[...links.values()]
            .filter(
              (link) =>
                link.link_type === 'species.descended_from' &&
                ids.has(link.source_id) &&
                ids.has(link.target_id),
            )
            .map((link) => ({
              id: link.id,
              kind: 'descended_from',
              source_id: link.source_id,
              target_id: link.target_id,
            })),
          ...found
            .filter((species) => shown(species.parent_id))
            .map((species) => ({
              id: `subspecies:${species.id}`,
              kind: 'subspecies',
              source_id: species.id,
              target_id: species.parent_id,
            })),
        ],
        truncated: false,
      })
    }),
    // The languages module's lexicon: headword/romanization prefix or gloss words, by headword.
    http.get('*/api/v1/vaults/v1/m/languages/:language/lexicon', ({ request, params }) => {
      const url = new URL(request.url)
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const pos = url.searchParams.get('pos')
      const tag = url.searchParams.get('tag')
      const items = [...lexicon.values()]
        .filter((entry) => entry.language_id === params.language && entry.deleted_at === null)
        .filter(
          (entry) =>
            q === '' ||
            entry.headword.toLowerCase().startsWith(q) ||
            (entry.romanization ?? '').toLowerCase().startsWith(q) ||
            entry.definitions.some((d) => d.gloss.toLowerCase().includes(q)),
        )
        .filter((entry) => pos === null || entry.part_of_speech === pos)
        .filter((entry) => tag === null || entry.tags.includes(tag))
        .sort((a, b) => (a.headword < b.headword ? -1 : a.headword > b.headword ? 1 : 0))
      return HttpResponse.json(paged(items, url))
    }),
    http.get('*/api/v1/vaults/v1/m/languages/lexicon/:id', ({ params }) => {
      const entry = lexicon.get(String(params.id))
      return entry?.deleted_at === null
        ? HttpResponse.json(entry)
        : HttpResponse.json(
            { status: 404, code: 'not_found', title: 'Not found', detail: 'No such entry.' },
            { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
          )
    }),
    http.post('*/api/v1/vaults/v1/m/languages/:language/lexicon', async ({ request, params }) => {
      const body = await record(request)
      lexiconSeq += 1
      const entry = lexiconOut({
        ...(body as unknown as LexiconRow),
        id: `w${lexiconSeq}`,
        language_id: String(params.language),
      })
      lexicon.set(entry.id, entry)
      return HttpResponse.json(lexiconWrite(entry), { status: 201 })
    }),
    http.patch('*/api/v1/vaults/v1/m/languages/lexicon/:id', async ({ request, params }) => {
      const body = await record(request)
      const entry = lexicon.get(String(params.id))
      if (!entry) return new HttpResponse(null, { status: 404 })
      const change = { ...body }
      delete change.revision
      const updated = lexiconOut({
        ...entry,
        ...(change as Partial<LexiconRow>),
        revision: entry.revision + 1,
      })
      lexicon.set(updated.id, updated)
      return HttpResponse.json(lexiconWrite(updated))
    }),
    http.delete('*/api/v1/vaults/v1/m/languages/lexicon/:id', async ({ request, params }) => {
      await record(request)
      const entry = lexicon.get(String(params.id))
      if (!entry) return new HttpResponse(null, { status: 404 })
      const deleted = { ...entry, deleted_at: '2026-10-11T11:00:00.000000+00:00' }
      lexicon.set(deleted.id, deleted)
      return HttpResponse.json(lexiconWrite(deleted))
    }),
    http.post(
      '*/api/v1/vaults/v1/m/languages/:language/lexicon/import',
      async ({ request, params }) => {
        // Rows without a headword are problems; a real import without problems creates them all.
        const body = (await record(request)) as {
          csv: string
          columns: Record<string, string> | null
        }
        const dryRun = new URL(request.url).searchParams.get('dry_run') === 'true'
        const [header = '', ...lines] = body.csv.trim().split('\n')
        const headers = header.split(',').map((cell) => cell.trim())
        const columns =
          body.columns ?? Object.fromEntries(headers.map((name) => [name, name.toLowerCase()]))
        const field = (cells: string[], name: string) => {
          const at = headers.findIndex((h) => columns[h] === name)
          return at < 0 ? '' : (cells[at] ?? '').trim()
        }
        const rows = lines.map((line) => line.split(','))
        const errors = rows.flatMap((cells, index) =>
          field(cells, 'headword') === ''
            ? [{ row: index + 1, column: null, message: 'A headword is required.' }]
            : [],
        )
        let created = 0
        if (!dryRun && errors.length === 0) {
          for (const cells of rows) {
            lexiconSeq += 1
            const gloss = field(cells, 'definitions')
            const entry = lexiconOut({
              id: `w${lexiconSeq}`,
              language_id: String(params.language),
              headword: field(cells, 'headword'),
              definitions: gloss === '' ? [] : [{ gloss }],
            })
            lexicon.set(entry.id, entry)
            created += 1
          }
        }
        return HttpResponse.json({
          rows: rows.length,
          created,
          columns,
          errors,
          affected: created > 0 ? { entities: [String(params.language)], ...NOTHING } : null,
        })
      },
    ),
    // The languages module's family graph (docs/modules/languages.md).
    http.get('*/api/v1/vaults/v1/m/languages/family-tree', () => {
      const languages = [...rows.values()]
        .filter((entity) => entity.kind === 'language' && entity.deleted_at === null)
        .sort((a, b) => a.name.localeCompare(b.name))
      const ids = new Set(languages.map((language) => language.id))
      const kinds: Record<string, string> = {
        'languages.descended_from': 'descended_from',
        'languages.borrowed_from': 'borrowed_from',
      }
      return HttpResponse.json({
        nodes: languages.map((language) => ({
          id: language.id,
          name: language.name,
          visibility: language.visibility,
          dimension_id: language.dimension_id,
          parent_id:
            language.parent_id !== null && ids.has(language.parent_id) ? language.parent_id : null,
        })),
        edges: [
          ...[...links.values()]
            .filter(
              (link) =>
                kinds[link.link_type] !== undefined &&
                ids.has(link.source_id) &&
                ids.has(link.target_id),
            )
            .map((link) => ({
              id: link.id,
              kind: kinds[link.link_type],
              source_id: link.source_id,
              target_id: link.target_id,
            })),
          ...languages
            .filter((language) => language.parent_id !== null && ids.has(language.parent_id))
            .map((language) => ({
              id: `dialect:${language.id}`,
              kind: 'dialect',
              source_id: language.id,
              target_id: language.parent_id,
            })),
        ],
        truncated: false,
      })
    }),
    // The groups module's reads (docs/modules/groups.md).
    http.get('*/api/v1/vaults/v1/m/groups/:id/members', ({ request, params }) => {
      const inside = new URL(request.url).searchParams.get('include_subgroups') === 'true'
      const groups = [String(params.id)]
      for (let i = 0; inside && i < groups.length; i++) {
        for (const entity of rows.values()) {
          if (entity.kind === 'group' && entity.parent_id === groups[i]) groups.push(entity.id)
        }
      }
      return HttpResponse.json({
        items: groups.flatMap((group) =>
          entityLinks(group)
            .filter((item) => item.link.link_type === 'groups.member_of' && item.direction === 'in')
            .map((item) => ({ group_id: group, item })),
        ),
      })
    }),
    http.get('*/api/v1/vaults/v1/m/groups/:id/leaders', ({ params }) =>
      HttpResponse.json({
        items: entityLinks(String(params.id))
          .filter((item) => item.link.link_type === 'groups.led_by' && item.direction === 'out')
          .map((item) => ({ item, from_t: null, to_t: null })),
      }),
    ),
    http.get('*/api/v1/vaults/v1/m/groups/:id/territory', ({ params }) =>
      HttpResponse.json({
        items: entityLinks(String(params.id)).filter(
          (item) => item.link.link_type === 'groups.controls' && item.direction === 'out',
        ),
      }),
    ),
    // The characters module's reads (docs/modules/characters.md).
    http.get('*/api/v1/vaults/v1/m/characters/:id/relationships', ({ params }) => {
      const category = (key: string) =>
        /^characters\.(parent_of|sibling_of|spouse_of)$/.test(key)
          ? 'family'
          : key === 'characters.relationship' || key.startsWith('custom.')
            ? 'custom'
            : key.startsWith('characters.')
              ? 'social'
              : null
      const items = entityLinks(String(params.id))
      return HttpResponse.json({
        groups: ['family', 'social', 'custom'].map((name) => ({
          category: name,
          items: items.filter((item) => category(item.link.link_type) === name),
        })),
      })
    }),
    // The family tree: relatives within `up`/`down` generations through family links
    // (parents ±1, spouses and siblings 0), and the family links between them.
    http.get('*/api/v1/vaults/v1/m/characters/:id/family-tree', ({ request, params }) => {
      const url = new URL(request.url)
      const root = found(params.id)
      if (root?.kind !== 'character') return new HttpResponse(null, { status: 404 })
      const up = Number(url.searchParams.get('up') ?? '3')
      const down = Number(url.searchParams.get('down') ?? '3')
      const kinds: Record<string, 'parent' | 'spouse' | 'sibling'> = {
        'characters.parent_of': 'parent',
        'characters.spouse_of': 'spouse',
        'characters.sibling_of': 'sibling',
      }
      if (url.searchParams.get('include_spouses') === 'false') delete kinds['characters.spouse_of']
      if (url.searchParams.get('include_siblings') === 'false') delete kinds['characters.sibling_of']
      const family = [...links.values()].filter(
        (link) =>
          kinds[link.link_type] !== undefined &&
          found(link.source_id)?.deleted_at === null &&
          found(link.target_id)?.deleted_at === null,
      )
      const generation = new Map([[root.id, 0]])
      const queue = [root.id]
      for (let id = queue.shift(); id !== undefined; id = queue.shift()) {
        const at = generation.get(id) ?? 0
        for (const link of family) {
          const kind = kinds[link.link_type]
          const [other, step] =
            link.source_id === id
              ? [link.target_id, kind === 'parent' ? 1 : 0]
              : link.target_id === id
                ? [link.source_id, kind === 'parent' ? -1 : 0]
                : [null, 0]
          if (other === null || generation.has(other)) continue
          if (at + step < -up || at + step > down) continue
          generation.set(other, at + step)
          queue.push(other)
        }
      }
      return HttpResponse.json({
        root_id: root.id,
        people: [...generation.entries()].map(([id, at]) => ({
          id,
          name: found(id)?.name ?? id,
          visibility: found(id)?.visibility ?? 'public',
          generation: at,
          from_t: null,
          to_t: null,
        })),
        edges: family
          .filter((link) => generation.has(link.source_id) && generation.has(link.target_id))
          .map((link) => ({
            id: link.id,
            kind: kinds[link.link_type],
            source_id: link.source_id,
            target_id: link.target_id,
            relation: (link.data as { kind?: string } | undefined)?.kind ?? null,
          })),
        truncated: false,
      })
    }),
    http.get('*/api/v1/vaults/v1/m/characters/:id/life', ({ params }) => {
      const id = String(params.id)
      const items = [...links.values()]
        .filter((link) => link.link_type === 'core.participant' && link.target_id === id)
        .map((link) => ({ link, event: found(link.source_id) }))
        .filter(({ event }) => event?.deleted_at === null)
        .map(({ link, event }) => {
          const start = (event?.ext as { start_t?: string } | undefined)?.start_t ?? '0'
          return {
            id: event?.id ?? '',
            name: event?.name ?? '',
            visibility: 'public',
            start_t: start,
            end_t: start,
            time_status: 'ok',
            importance: 3,
            display: { calendar_id: 'absolute', start: `${start} s`, end: `${start} s` },
            roles: link.role ? [link.role] : [],
          }
        })
        .sort((a, b) => (BigInt(a.start_t) < BigInt(b.start_t) ? -1 : 1))
      return HttpResponse.json({ items, truncated: false })
    }),
    // The locations module's reads (docs/modules/locations.md).
    http.get('*/api/v1/vaults/v1/m/locations/tree', ({ request }) => {
      const url = new URL(request.url)
      const root = url.searchParams.get('root')
      const depth = Number(url.searchParams.get('depth') ?? '1')
      const live = [...rows.values()].filter(
        (entity) => entity.kind === 'location' && entity.deleted_at === null,
      )
      const level = (parent: string | null, remaining: number): unknown[] =>
        live
          .filter((entity) => entity.parent_id === parent)
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((entity) => {
            const count = live.filter((child) => child.parent_id === entity.id).length
            const type = entity.fields.location_type
            return {
              id: entity.id,
              name: entity.name,
              visibility: entity.visibility,
              dimension_id: entity.dimension_id,
              parent_id: entity.parent_id,
              multiversal: entity.dimension_id === null,
              location_type: typeof type === 'string' ? type : null,
              child_count: count,
              children: remaining > 1 ? level(entity.id, remaining - 1) : null,
            }
          })
      return HttpResponse.json({ root_id: root, items: level(root, depth), truncated: false })
    }),
    http.get('*/api/v1/vaults/v1/m/locations/:id/events', ({ request, params }) => {
      const url = new URL(request.url)
      const inside = url.searchParams.get('include_descendants') !== 'false'
      const sites = [String(params.id)]
      for (let i = 0; inside && i < sites.length; i++) {
        for (const entity of rows.values()) {
          if (entity.kind === 'location' && entity.parent_id === sites[i]) sites.push(entity.id)
        }
      }
      const items = [...rows.values()]
        .filter((entity) => entity.kind === 'event' && entity.deleted_at === null)
        .map((entity) => ({
          entity,
          at: [...links.values()]
            .filter(
              (link) =>
                link.link_type === 'locations.event_site' &&
                link.source_id === entity.id &&
                sites.includes(link.target_id),
            )
            .map((link) => link.target_id),
          start: (entity.ext as { start_t?: string } | undefined)?.start_t ?? '0',
        }))
        .filter((item) => item.at.length > 0)
        .sort((a, b) => (BigInt(a.start) < BigInt(b.start) ? -1 : 1))
        .map(({ entity, at, start }) => ({
          id: entity.id,
          name: entity.name,
          visibility: entity.visibility,
          start_t: start,
          end_t: start,
          time_status: 'ok',
          importance: 3,
          display: { calendar_id: 'absolute', start: `${start} s`, end: `${start} s` },
          site_ids: at,
        }))
      return HttpResponse.json({ items, truncated: false })
    }),
    http.get('*/api/v1/vaults/v1/m/locations/:id/residents', ({ params }) =>
      HttpResponse.json({
        items: entityLinks(String(params.id)).filter(
          (item) => item.link.link_type === 'locations.resides_in' && item.direction === 'in',
        ),
      }),
    ),
    http.get('*/api/v1/vaults/v1/entities/field-values', ({ request }) => {
      const url = new URL(request.url)
      const kindKey = url.searchParams.get('kind')
      const field = url.searchParams.get('field') ?? ''
      const counts = new Map<string, number>()
      for (const entity of rows.values()) {
        const value = entity.fields[field]
        if (entity.kind !== kindKey || entity.deleted_at !== null) continue
        if (typeof value === 'string') counts.set(value, (counts.get(value) ?? 0) + 1)
      }
      const items = [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([value, count]) => ({ value, count }))
      return HttpResponse.json({ items })
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
    http.get('*/api/v1/vaults/v1/search', ({ request }) => {
      // Names and body text containing the query; a body match gets a snippet.
      const url = new URL(request.url)
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const kinds = url.searchParams.getAll('kind')
      const dimension = url.searchParams.get('dimension')
      const items = [...rows.values()]
        .filter((entity) => entity.deleted_at === null)
        .filter((entity) => kinds.length === 0 || kinds.includes(entity.kind))
        .filter((entity) => dimension === null || entity.dimension_id === dimension)
        .flatMap((entity) => {
          const text = bodyText(entity.body)
          const at = text.toLowerCase().indexOf(q)
          if (!entity.name.toLowerCase().includes(q) && at < 0) return []
          return [
            {
              doc_type: 'entity',
              doc_id: entity.id,
              entity_id: entity.id,
              kind: entity.kind,
              name: entity.name,
              icon: null,
              color: null,
              dimension_id: entity.dimension_id,
              visibility: entity.visibility,
              snippet:
                at < 0
                  ? null
                  : {
                      source: 'body',
                      parts: [
                        { text: text.slice(0, at), match: false },
                        { text: text.slice(at, at + q.length), match: true },
                        { text: text.slice(at + q.length), match: false },
                      ],
                    },
            },
          ]
        })
      // Lexicon entries (`languages.lexicon_entry`): headword starts, or gloss words.
      const words = [...lexicon.values()]
        .filter((entry) => entry.deleted_at === null)
        .filter(() => kinds.length === 0 || kinds.includes('languages.lexicon_entry'))
        .filter(
          (entry) =>
            entry.headword.toLowerCase().startsWith(q) ||
            entry.definitions.some((d) => d.gloss.toLowerCase().includes(q)),
        )
        .map((entry) => ({
          doc_type: 'languages.lexicon_entry',
          doc_id: entry.id,
          entity_id: entry.language_id,
          kind: 'language',
          name: entry.headword,
          icon: 'book',
          color: null,
          dimension_id: null,
          visibility: entry.visibility,
          snippet: {
            source: 'summary',
            parts: [{ text: entry.definitions.map((d) => d.gloss).join('; '), match: false }],
          },
        }))
      return HttpResponse.json(paged([...items, ...words], url))
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
    http.get('*/api/v1/vaults/v1/entities/:id/links', ({ request, params }) => {
      // `type` and `direction` filter like the server's (symmetric links match both ways).
      const url = new URL(request.url)
      const only = url.searchParams.getAll('type')
      const direction = url.searchParams.get('direction') ?? 'both'
      const items = entityLinks(String(params.id))
        .filter((item) => only.length === 0 || only.includes(item.link.link_type))
        .filter(
          (item) =>
            direction === 'both' || item.direction === 'both' || item.direction === direction,
        )
      return HttpResponse.json({ items })
    }),
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
    http.get('*/api/v1/vaults/v1/settings', () => HttpResponse.json(settings)),
    http.patch('*/api/v1/vaults/v1/settings', async ({ request }) => {
      const body = (await record(request)) as Partial<typeof settings>
      settings = {
        defaults: { ...settings.defaults, ...body.defaults },
        backups: { ...settings.backups, ...body.backups },
      }
      return HttpResponse.json(settings)
    }),
    http.get('*/api/v1/vaults/v1/backups', () => HttpResponse.json({ items: backups })),
    http.post('*/api/v1/vaults/v1/backups', async ({ request }) => {
      const body = (await record(request)) as { include_media?: boolean }
      const backup: BackupRow = {
        id: `b${String(backups.length + 1)}`,
        kind: 'manual',
        reason: null,
        created_at: '2026-10-11T12:00:00.000000+00:00',
        size: 2048,
        includes_media: body.include_media ?? true,
        app_version: '0.2.0',
        schema_revision: 'abc',
      }
      backups.unshift(backup)
      return HttpResponse.json(backup, { status: 201 })
    }),
    http.post('*/api/v1/vaults/restore', () => {
      // (jsdom's XHR uploads reach MSW without their multipart body: failures are counted.)
      writes.push({ method: 'POST', path: '/vaults/restore', body: null })
      if (restoreFailures > 0) {
        restoreFailures -= 1
        return problem(422, 'invalid_backup', 'Invalid backup', 'This file isn’t a Lore backup.')
      }
      return HttpResponse.json(makeVault('v9', 'Atlas (restored)'), { status: 201 })
    }),
    http.patch('*/api/v1/vaults/v1/modules/:id', async ({ request, params }) => {
      const body = (await record(request)) as { enabled: boolean; cascade?: boolean }
      const states = moduleStates ?? []
      const target = states.find((state) => state.id === params.id)
      if (!target) return problem(404, 'module_not_found', 'Not found', 'No such module.')
      const enabled: string[] = []
      const disabled: string[] = []
      if (body.enabled) {
        const on = (state: ModuleStateRow) => {
          for (const dependency of state.depends_on) {
            const found = states.find((candidate) => candidate.id === dependency)
            if (found) on(found)
          }
          if (!state.enabled) {
            state.enabled = true
            enabled.push(state.id)
          }
        }
        on(target)
      } else {
        const dependents = states.filter(
          (state) => state.enabled && state.depends_on.includes(target.id),
        )
        if (dependents.length > 0 && body.cascade !== true) {
          return HttpResponse.json(
            {
              type: 'about:blank',
              status: 409,
              code: 'module_has_dependents',
              title: 'Module has dependents',
              detail: 'Other modules need it.',
              context: { dependents: dependents.map((state) => state.id) },
            },
            { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
          )
        }
        for (const state of [target, ...dependents]) {
          state.enabled = false
          disabled.push(state.id)
        }
      }
      return HttpResponse.json({ enabled, disabled, modules: states })
    }),
    http.post('*/api/v1/vaults/v1/link-types', async ({ request }) => {
      const body = await record(request)
      const label = String(body.label)
      const key =
        typeof body.key === 'string'
          ? body.key
          : `custom.${label.toLowerCase().replaceAll(' ', '_')}`
      const created = { ...linkType(key, label, body), user_defined: true, revision: 1 }
      types.push(created)
      return HttpResponse.json(created, { status: 201 })
    }),
    http.patch('*/api/v1/vaults/v1/link-types/:key', async ({ request, params }) => {
      const body = await record(request)
      const type = types.find((candidate) => candidate.key === params.key)
      if (!type) return new HttpResponse(null, { status: 404 })
      const change = Object.fromEntries(Object.entries(body).filter(([key]) => key !== 'revision'))
      Object.assign(type, change, { revision: (type.revision ?? 1) + 1 })
      return HttpResponse.json(type)
    }),
    http.delete('*/api/v1/vaults/v1/link-types/:key', async ({ request, params }) => {
      await record(request)
      const used = [...links.values()].filter((link) => link.link_type === params.key).length
      if (used > 0) {
        return HttpResponse.json(
          {
            type: 'about:blank',
            status: 409,
            code: 'conflict',
            title: 'Conflict',
            detail: `${String(used)} links use this link type.`,
            context: { links: used },
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }
      types.splice(
        types.findIndex((candidate) => candidate.key === params.key),
        1,
      )
      return HttpResponse.json({ key: params.key })
    }),
    http.get('*/api/v1/vaults/v1/changes', ({ request }) => {
      const url = new URL(request.url)
      const origins = url.searchParams.getAll('origin')
      const items = changesets
        .filter((changeset) => origins.length === 0 || origins.includes(changeset.origin ?? 'ui'))
        .map(summary)
      return HttpResponse.json(paged(items, url))
    }),
    http.get('*/api/v1/vaults/v1/changes/:id', ({ params }) => {
      const changeset = changesets.find((candidate) => candidate.id === params.id)
      return changeset
        ? HttpResponse.json(detail(changeset))
        : new HttpResponse(null, { status: 404 })
    }),
    http.get('*/api/v1/vaults/v1/entities/:id/history', ({ request, params }) => {
      const items = changesets
        .filter((changeset) => changeset.entities.some((entity) => entity.id === params.id))
        .map(summary)
      return HttpResponse.json(paged(items, new URL(request.url)))
    }),
    http.post('*/api/v1/vaults/v1/changes/:id/revert', async ({ request, params }) => {
      await record(request)
      const changeset = changesets.find((candidate) => candidate.id === params.id)
      if (!changeset) return new HttpResponse(null, { status: 404 })
      if (changeset.conflict) {
        return HttpResponse.json(
          {
            type: 'urn:lore:problem:revert_conflict',
            title: 'Revert conflict',
            status: 409,
            code: 'revert_conflict',
            detail: 'The undo was refused.',
            context: { rows: [], problems: [], ...changeset.conflict },
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }
      const undo: FakeChangeset = {
        id: `undo-${changeset.id}`,
        summary: `Undid “${changeset.summary}”`,
        origin: 'undo',
        entities: changeset.entities,
        changes: [],
        reverts_changeset_id: changeset.id,
      }
      changeset.reverted_by_changeset_id = undo.id
      changesets.unshift(undo)
      return HttpResponse.json({
        changeset: detail(undo),
        affected: { entities: changeset.entities.map((entity) => entity.id), ...NOTHING },
      })
    }),
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
      const refused = refuse(body)
      if (refused !== null) return refused
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
        ...(body.ext !== undefined && body.ext !== null
          ? { ext: { ...(entity.ext ?? {}), ...body.ext } }
          : {}),
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
      const refused = refuse(body)
      if (refused !== null) return refused
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
