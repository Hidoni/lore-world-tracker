import type { components } from '@/api'

import { NotInExport, StaticProblem, type Handler, type Load } from './static-core'

/**
 * Entity reads of a static export (#374, visibility-and-sharing.md §8). The builder writes an
 * index of the listed entities (their summaries, the server's own order for every sort, tags,
 * aliases, branch origin, existence over time) and one shard of recorded answers per entity,
 * with the as-of answers recorded once per interval between the moments they can change. Lists
 * and trees are filtered, ordered and paged here from the index; everything else is a lookup.
 */

type Schemas = components['schemas']
type Summary = Schemas['EntitySummary']
type Existence = NonNullable<Summary['existence']>
/** `[[moment, answer], …]`: the answer from each moment on (the first moment is 0). */
type Intervals<T> = [string, T][]

interface IndexEntry {
  summary: Summary
  tags: string[]
  aliases: string[]
  origin: string | null
  multiversal: boolean
  existence?: Record<string, Intervals<Existence>>
}

interface TimelineInfo {
  dimension: string
  prime: boolean
  lineage: string[]
}

interface Index {
  entities: Record<string, IndexEntry>
  orders: Record<string, string[]>
  timelines: Record<string, TimelineInfo>
}

interface Shard {
  entity: Schemas['EntityOut']
  links: Schemas['EntityLinks']
  backlinks: Schemas['Backlinks']
  unlinked: Schemas['UnlinkedMentions']
  facts: Record<string, Schemas['FactList']>
  caused?: Schemas['FactList']
  as_of: Record<
    string,
    {
      state: Intervals<Schemas['EntityStateOut']>
      links: Intervals<Schemas['EntityLinks']>
      backlinks: Intervals<Schemas['Backlinks']>
    }
  >
}

/** What lists derive from the index, once per loaded index. */
interface Derived {
  index: Index
  children: Map<string, string[]>
  primes: Map<string, string>
}

const derived = new WeakMap<object, Derived>()

async function loadIndex(load: Load, vault: string): Promise<Derived> {
  const index = (await load(`vaults/${vault}/static/index`)) as Index
  let found = derived.get(index)
  if (!found) {
    const children = new Map<string, string[]>()
    for (const id of index.orders.sort_key ?? []) {
      const parent = index.entities[id]?.summary.parent_id
      if (parent) children.set(parent, [...(children.get(parent) ?? []), id])
    }
    const primes = new Map<string, string>()
    for (const [id, timeline] of Object.entries(index.timelines)) {
      if (timeline.prime) primes.set(timeline.dimension, id)
    }
    found = { index, children, primes }
    derived.set(index, found)
  }
  return found
}

function notFound(what: string): StaticProblem {
  return new StaticProblem(404, 'not_found', 'Not found', `No ${what}.`)
}

function invalid(detail: string): StaticProblem {
  return new StaticProblem(422, 'invalid_input', 'Invalid input', detail)
}

async function loadShard(load: Load, vault: string, id: string): Promise<Shard> {
  try {
    return (await load(`vaults/${vault}/static/entities/${id}`)) as Shard
  } catch (error) {
    if (error instanceof NotInExport) throw notFound(`entity ${id}`)
    throw error
  }
}

/** The answer recorded for the last moment at or before `at`. */
export function pick<T>(intervals: Intervals<T>, at: string): T | undefined {
  const t = BigInt(at)
  let found: T | undefined
  for (const [moment, answer] of intervals) {
    if (BigInt(moment) > t) break
    found = answer
  }
  return found
}

function lowerAscii(text: string): string {
  return text.replace(/[A-Z]/g, (c) => c.toLowerCase())
}

/** Whether an entity is shown in a timeline's view (`entity_scope`): branch-only ones in theirs. */
function inScope(derived: Derived, entry: IndexEntry, timeline: string | null): boolean {
  if (entry.origin === null) return true
  if (timeline === null) return false
  return derived.index.timelines[timeline]?.lineage.includes(entry.origin) ?? false
}

function checkTimeline(derived: Derived, timeline: string | null): void {
  if (timeline !== null && !(timeline in derived.index.timelines)) {
    throw notFound(`timeline ${timeline}`)
  }
}

/** The cursor's timeline (`as_of_for`): the given one, else the prime timeline of `dimension`. */
function cursorTimeline(
  derived: Derived,
  timeline: string | null,
  dimension: string | null | undefined,
): string {
  const found = timeline ?? (dimension ? derived.primes.get(dimension) : undefined)
  if (found === undefined) throw invalid('`at` needs a timeline here.')
  return found
}

function existenceAt(entry: IndexEntry, timeline: string, at: string): Existence {
  const intervals = entry.existence?.[timeline]
  return (intervals && pick(intervals, at)) ?? 'unknown'
}

/** Our own cursors: the position after the last item returned (only this file reads them). */
function decodeCursor(cursor: string | null): number {
  if (cursor === null) return 0
  const offset = Number(atob(cursor))
  if (!Number.isInteger(offset) || offset < 0) throw invalid('The cursor is invalid.')
  return offset
}

function page<T>(items: T[], cursor: string | null, limit: number) {
  const start = decodeCursor(cursor)
  const end = start + limit
  return {
    items: items.slice(start, end),
    next_cursor: end < items.length ? btoa(String(end)) : null,
  }
}

function limitOf(params: URLSearchParams, fallback: number): number {
  const value = params.get('limit')
  return value === null ? fallback : Number(value)
}

function ordered(derived: Derived, sort: string): string[] {
  const descending = sort.startsWith('-')
  const order = derived.index.orders[descending ? sort.slice(1) : sort]
  if (!order) throw invalid(`Unknown sort ${sort}.`)
  return descending ? [...order].reverse() : order
}

/** `_dimension`: the dimension's entities and, unless excluded, the multiversal ones. */
function inDimension(entry: IndexEntry, dimension: string | null, multiversal = true): boolean {
  if (dimension === null) return true
  return entry.summary.dimension_id === dimension || (multiversal && entry.multiversal)
}

const listEntities: Handler = async (load, _route, params, groups) => {
  const [vault = ''] = groups
  const derived = await loadIndex(load, vault)
  const timeline = params.get('timeline')
  checkTimeline(derived, timeline)
  const kinds = params.getAll('kind')
  const dimension = params.get('dimension')
  const multiversal = params.get('include_multiversal') !== 'false'
  const parent = params.get('parent')
  const tags = params.getAll('tag')
  const q = params.get('q')
  const at = params.get('at')
  const cursorIn = at === null ? null : cursorTimeline(derived, timeline, dimension)
  const items: Summary[] = []
  for (const id of ordered(derived, params.get('sort') ?? 'name')) {
    const entry = derived.index.entities[id]
    if (!entry || !inScope(derived, entry, timeline)) continue
    const { summary } = entry
    if (kinds.length > 0 && !kinds.includes(summary.kind)) continue
    if (!inDimension(entry, dimension, multiversal)) continue
    if (parent !== null && summary.parent_id !== parent) continue
    if (!tags.every((tag) => entry.tags.includes(tag))) continue
    if (q) {
      const prefix = lowerAscii(q)
      const names = [summary.name, ...entry.aliases].map(lowerAscii)
      if (!names.some((name) => name.startsWith(prefix))) continue
    }
    if (at !== null && cursorIn !== null) {
      const existence = existenceAt(entry, cursorIn, at)
      if (existence === 'not_exists') continue
      items.push({ ...summary, existence })
    } else {
      items.push(summary)
    }
  }
  return page(items, params.get('cursor'), limitOf(params, 50))
}

interface TreeQuery {
  dimension: string | null
  kinds: string[]
  timeline: string | null
}

/** `_in_tree`: shown in the timeline's view, of the kinds asked, in the dimension. */
function inTree(derived: Derived, entry: IndexEntry | undefined, query: TreeQuery): boolean {
  if (!entry || !inScope(derived, entry, query.timeline)) return false
  if (query.kinds.length > 0 && !query.kinds.includes(entry.summary.kind)) return false
  return inDimension(entry, query.dimension)
}

function treeNodes(
  derived: Derived,
  ids: string[],
  query: TreeQuery,
  params: URLSearchParams,
  groupBy: string | null,
): Schemas['TreePage'] {
  const at = params.get('at')
  const cursorIn = at === null ? null : cursorTimeline(derived, query.timeline, query.dimension)
  const nodes: Schemas['TreeNode'][] = []
  for (const id of ids) {
    const entry = derived.index.entities[id]
    if (!entry) continue
    let existence: Existence | null = null
    if (at !== null && cursorIn !== null) {
      existence = existenceAt(entry, cursorIn, at)
      if (existence === 'not_exists') continue
    }
    const counts: Record<string, number> = {}
    for (const child of derived.children.get(id) ?? []) {
      const childEntry = derived.index.entities[child]
      if (childEntry && inTree(derived, childEntry, query)) {
        counts[childEntry.summary.kind] = (counts[childEntry.summary.kind] ?? 0) + 1
      }
    }
    const { summary } = entry
    const group = groupBy === null ? null : summary.fields[groupBy]
    nodes.push({
      id,
      kind: summary.kind,
      name: summary.name,
      icon: summary.icon,
      color: summary.color,
      dimension_id: summary.dimension_id,
      parent_id:
        summary.parent_id !== null && summary.parent_id in derived.index.entities
          ? summary.parent_id
          : null,
      multiversal: entry.multiversal,
      visibility: summary.visibility,
      sort_key: summary.sort_key,
      has_children: Object.keys(counts).length > 0,
      child_counts: counts,
      group: typeof group === 'string' && group.trim() !== '' ? group.trim() : null,
      existence,
    })
  }
  return page(nodes, params.get('cursor'), limitOf(params, 200))
}

const tree: Handler = async (load, _route, params, groups) => {
  const [vault = ''] = groups
  const derived = await loadIndex(load, vault)
  const query: TreeQuery = {
    dimension: params.get('dimension'),
    kinds: params.getAll('kind'),
    timeline: params.get('timeline'),
  }
  checkTimeline(derived, query.timeline)
  const groupBy = params.get('group_by')
  if (groupBy !== null && new Set(query.kinds).size !== 1) {
    throw invalid('Grouping needs exactly one kind.')
  }
  const parent = params.get('parent')
  const ids = (derived.index.orders.sort_key ?? []).filter((id) => {
    const entry = derived.index.entities[id]
    if (!inTree(derived, entry, query)) return false
    const parentId = entry?.summary.parent_id ?? null
    if (parent !== null) return parentId === parent
    return parentId === null || !inTree(derived, derived.index.entities[parentId], query)
  })
  return treeNodes(derived, ids, query, params, groupBy)
}

const children: Handler = async (load, _route, params, groups) => {
  const [vault = '', id = ''] = groups
  const derived = await loadIndex(load, vault)
  if (!(id in derived.index.entities)) throw notFound(`entity ${id}`)
  // Every dimension, so `at` needs an explicit `timeline` (`422` like the server's).
  const query: TreeQuery = { dimension: null, kinds: params.getAll('kind'), timeline: null }
  const timeline = params.get('timeline')
  checkTimeline(derived, timeline)
  const ids = (derived.children.get(id) ?? []).filter((child) =>
    inTree(derived, derived.index.entities[child], query),
  )
  return treeNodes(derived, ids, { ...query, timeline }, params, null)
}

/** An entity's timeline for as-of reads: the given one, else its dimension's prime timeline. */
function entityTimeline(derived: Derived, shard: Shard, timeline: string | null): string {
  return cursorTimeline(derived, timeline, shard.entity.dimension_id)
}

function asOf<K extends 'state' | 'links' | 'backlinks'>(
  shard: Shard,
  timeline: string,
  read: K,
  at: string,
): Shard['as_of'][string][K][number][1] {
  const recorded = shard.as_of[timeline]
  if (!recorded) throw notFound(`timeline ${timeline}`)
  const found = pick(recorded[read] as Intervals<Shard['as_of'][string][K][number][1]>, at)
  if (found === undefined) throw invalid('`at` is before the inception.')
  return found
}

function stateAt(shard: Shard, timeline: string, at: string): Schemas['EntityStateOut'] {
  return { ...asOf(shard, timeline, 'state', at), at: at as Schemas['EntityStateOut']['at'] }
}

async function shardOf(load: Load, groups: readonly string[]) {
  const [vault = '', id = ''] = groups
  return { derived: await loadIndex(load, vault), shard: await loadShard(load, vault, id), id }
}

const entity: Handler = async (load, _route, params, groups) => {
  const { derived, shard } = await shardOf(load, groups)
  const at = params.get('at')
  if (at === null) return shard.entity
  const timeline = entityTimeline(derived, shard, params.get('timeline'))
  return { ...shard.entity, state: stateAt(shard, timeline, at) }
}

const state: Handler = async (load, _route, params, groups) => {
  const { derived, shard } = await shardOf(load, groups)
  const at = params.get('at')
  if (at === null) throw invalid('`at` is required.')
  return stateAt(shard, entityTimeline(derived, shard, params.get('timeline')), at)
}

const facts: Handler = async (load, _route, params, groups) => {
  const { shard } = await shardOf(load, groups)
  const timeline = params.get('timeline') ?? ''
  const recorded = shard.facts[timeline]
  if (!recorded) throw notFound(`timeline ${timeline}`)
  const field = params.get('field')
  return field === null
    ? recorded
    : { ...recorded, items: recorded.items.filter((f) => f.field_key === field) }
}

const links: Handler = async (load, _route, params, groups) => {
  const { derived, shard, id } = await shardOf(load, groups)
  const at = params.get('at')
  const recorded =
    at === null
      ? shard.links
      : asOf(shard, entityTimeline(derived, shard, params.get('timeline')), 'links', at)
  const [vault = ''] = groups
  const types = params.getAll('type')
  const direction = params.get('direction') ?? 'both'
  const symmetric = new Set(
    ((await load(`vaults/${vault}/link-types`)) as Schemas['LinkTypeList']).items
      .filter((type) => type.symmetric)
      .map((type) => type.key),
  )
  return {
    ...recorded,
    items: recorded.items.filter(({ link }) => {
      if (types.length > 0 && !types.includes(link.link_type)) return false
      if (direction === 'out') return link.source_id === id || symmetric.has(link.link_type)
      if (direction === 'in') return link.target_id === id || symmetric.has(link.link_type)
      return true
    }),
  }
}

const backlinks: Handler = async (load, _route, params, groups) => {
  const { derived, shard } = await shardOf(load, groups)
  const at = params.get('at')
  if (at === null) return shard.backlinks
  return asOf(shard, entityTimeline(derived, shard, params.get('timeline')), 'backlinks', at)
}

const unlinked: Handler = async (load, _route, params, groups) => {
  const { shard } = await shardOf(load, groups)
  const limit = limitOf(params, 50)
  const { items, truncated } = shard.unlinked
  return {
    ...shard.unlinked,
    items: items.slice(0, limit),
    truncated: truncated || items.length > limit,
  }
}

const causedFacts: Handler = async (load, _route, params, groups) => {
  const event = params.get('source_event')
  if (event === null) throw new NotInExport('facts')
  const [vault = ''] = groups
  const { shard } = await shardOf(load, [vault, event])
  return shard.caused ?? { items: [] }
}

const V = '^vaults/([^/]+)'
const E = `${V}/entities/([^/]+)`

/** The entity reads of a static export, by route. */
export const ENTITY_HANDLERS: readonly (readonly [RegExp, Handler])[] = [
  [new RegExp(`${V}/entities$`), listEntities],
  [new RegExp(`${V}/tree$`), tree],
  [new RegExp(`${V}/facts$`), causedFacts],
  [new RegExp(`${E}/children$`), children],
  [new RegExp(`${E}/state$`), state],
  [new RegExp(`${E}/facts$`), facts],
  [new RegExp(`${E}/links$`), links],
  [new RegExp(`${E}/backlinks$`), backlinks],
  [new RegExp(`${E}/unlinked-mentions$`), unlinked],
  [new RegExp(`${E}$`), entity],
]
