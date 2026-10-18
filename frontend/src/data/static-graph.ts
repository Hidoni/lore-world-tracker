import type { components } from '@/api'

import { NotInExport, type Handler, type Load } from './static-core'
import {
  checkTimeline,
  cursorTimeline,
  type Derived,
  existenceAt,
  inScope,
  type IndexEntry,
  invalid,
  loadIndex,
  notFound,
  pick,
} from './static-entities'

/**
 * The graph of a static export (#386, ADR 0016's exception), computed in the browser for any
 * filters, center, depth, limit and cursor: a port of `modules/graph/service.py` over the entity
 * index (nodes, tags, parents, existence) and `static/m/graph/graph` (`GraphReader.static_data`:
 * links with where they are valid in each timeline, and mentions). Nodes are ordered like the
 * server's; edges hold the same set in another order.
 */

type Graph = components['schemas']['Graph']
type GraphNode = Graph['nodes'][number]
type GraphEdge = Graph['edges'][number]

/** `[id, source, target, type, role, timeline]`. */
type LinkRow = [string, string, string, string, string | null, string | null]

interface GraphData {
  kinds: string[]
  links: LinkRow[]
  /** By timeline, by bounded link: `[[moment, valid], …]` where it changes. */
  valid: Record<string, Record<string, [string, boolean][]>>
  /** `[source, target, weight]`. */
  mentions: [string, string, number][]
}

interface Edge {
  source: string
  target: string
  kind: 'link' | 'mention' | 'parent'
  linkId: string | null
  linkType: string | null
  label: string | null
  weight: number
}

interface Query {
  dimension: string | null
  center: string | null
  depth: number
  kinds: string[]
  linkTypes: string[]
  tags: string[]
  mentions: boolean
  hierarchy: boolean
  timeline: string | null
  at: string | null
  limit: number
}

/** FastAPI's booleans. */
function bool(params: URLSearchParams, name: string): boolean {
  const value = params.get(name)
  if (value === null) return true
  const lower = value.toLowerCase()
  if (['true', '1', 'yes', 'on', 't', 'y'].includes(lower)) return true
  if (['false', '0', 'no', 'off', 'f', 'n'].includes(lower)) return false
  throw invalid(`${name} must be a boolean.`)
}

function int(params: URLSearchParams, name: string, fallback: number, max: number): number {
  const value = params.get(name)
  if (value === null) return fallback
  const n = Number(value)
  if (!/^-?\d+$/.test(value.trim()) || n < 1 || n > max) {
    throw invalid(`${name} must be an integer from 1 to ${max}.`)
  }
  return n
}

function queryOf(params: URLSearchParams): Query {
  return {
    dimension: params.get('dimension'),
    center: params.get('center'),
    depth: int(params, 'depth', 1, 4),
    kinds: params.getAll('kind'),
    linkTypes: params.getAll('link_type'),
    tags: params.getAll('tag'),
    mentions: bool(params, 'include_mentions'),
    hierarchy: bool(params, 'include_hierarchy'),
    timeline: params.get('timeline'),
    at: params.get('at'),
    limit: int(params, 'limit', 5000, 20000),
  }
}

async function dataOf(load: Load, vault: string): Promise<GraphData> {
  try {
    return (await load(`vaults/${vault}/static/m/graph/graph`)) as GraphData
  } catch (error) {
    // The module is off in this vault: its routes aren't there.
    if (error instanceof NotInExport) throw notFound('route')
    throw error
  }
}

/** Python's `sorted` on strings: by code point. */
function byCodePoint(a: string, b: string): number {
  const x = Array.from(a)
  const y = Array.from(b)
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = (x[i]?.codePointAt(0) ?? 0) - (y[i]?.codePointAt(0) ?? 0)
    if (d !== 0) return d
  }
  return x.length - y.length
}

class Reader {
  constructor(
    readonly derived: Derived,
    readonly data: GraphData,
    readonly query: Query,
    /** The cursor (`as_of_for`), or `null` without `at`. */
    readonly asOf: { timeline: string; at: string } | null,
  ) {}

  /** The node candidates (`_node_statement`): kinds, dimension, tags, branch scope. */
  candidates(): Map<string, IndexEntry> {
    const kinds = new Set(this.data.kinds)
    if (this.query.kinds.length > 0) {
      const asked = new Set(this.query.kinds)
      for (const kind of kinds) if (!asked.has(kind)) kinds.delete(kind)
    }
    const tags = new Set(this.query.tags)
    const found = new Map<string, IndexEntry>()
    for (const [id, entry] of Object.entries(this.derived.index.entities)) {
      const { summary } = entry
      if (!kinds.has(summary.kind)) continue
      if (
        this.query.dimension !== null &&
        summary.dimension_id !== this.query.dimension &&
        summary.dimension_id !== null
      )
        continue
      if (tags.size > 0 && !entry.tags.some((tag) => tags.has(tag))) continue
      if (!inScope(this.derived, entry, this.query.timeline)) continue
      found.set(id, entry)
    }
    return found
  }

  /** The existence shown at the cursor, or `null` when the node isn't shown then. */
  existence(entry: IndexEntry): GraphNode['existence'] | 'hidden' {
    if (this.asOf === null) return 'unknown'
    const shown = existenceAt(entry, this.asOf.timeline, this.asOf.at)
    return shown === 'not_exists' ? 'hidden' : shown
  }

  /** Every edge between two candidates, as `_edges` reads them (links, mentions, parents). */
  edges(candidates: Map<string, IndexEntry>): Edge[] {
    const { query, asOf } = this
    const types = new Set(query.linkTypes)
    const index = this.derived.index
    const timelines = new Set(
      query.timeline !== null
        ? (index.timelines[query.timeline]?.lineage ?? [])
        : Object.entries(index.timelines)
            .filter(([, t]) => t.prime)
            .map(([id]) => id),
    )
    const valid = asOf === null ? null : (this.data.valid[asOf.timeline] ?? {})
    const edges: Edge[] = []
    for (const [id, source, target, type, role, timeline] of this.data.links) {
      if (!candidates.has(source) || !candidates.has(target)) continue
      if (types.size > 0 && !types.has(type)) continue
      if (timeline !== null) {
        if (!timelines.has(timeline)) continue
        if (valid !== null && asOf !== null) {
          const intervals = valid[id]
          if (intervals === undefined || pick(intervals, asOf.at) !== true) continue
        }
      }
      edges.push({
        source,
        target,
        kind: 'link',
        linkId: id,
        linkType: type,
        label: role,
        weight: 1,
      })
    }
    if (query.mentions) {
      for (const [source, target, weight] of this.data.mentions) {
        if (candidates.has(source) && candidates.has(target)) {
          edges.push({
            source,
            target,
            kind: 'mention',
            linkId: null,
            linkType: null,
            label: null,
            weight,
          })
        }
      }
    }
    if (query.hierarchy) {
      for (const [id, entry] of candidates) {
        const parent = entry.summary.parent_id
        if (parent && candidates.has(parent)) {
          edges.push({
            source: parent,
            target: id,
            kind: 'parent',
            linkId: null,
            linkType: null,
            label: null,
            weight: 1,
          })
        }
      }
    }
    return edges
  }

  graph(): Graph {
    const candidates = this.candidates()
    const all = this.edges(candidates)
    const nodes = new Map<string, NonNullable<GraphNode['existence']>>()
    const found = new Map<string, Edge>()
    const add = (edges: Iterable<Edge>) => {
      for (const edge of edges) {
        if (edge.source === edge.target) continue
        found.set(
          `${edge.kind}\u0000${edge.linkId ?? ''}\u0000${edge.source}\u0000${edge.target}`,
          edge,
        )
      }
    }
    /** Adds the candidates among `ids` shown at the cursor (`_add_nodes`); returns them. */
    const addNodes = (ids: Iterable<string>, timed: boolean) => {
      const added: string[] = []
      for (const id of ids) {
        const entry = candidates.get(id)
        if (entry === undefined || nodes.has(id)) continue
        const shown = timed ? this.existence(entry) : 'unknown'
        if (shown === 'hidden' || shown === null) continue
        nodes.set(id, shown)
        added.push(id)
      }
      return added
    }
    if (this.query.center === null) {
      addNodes(candidates.keys(), true)
      add(all)
    } else {
      // Breadth-first from the center: each level, the edges touching the frontier.
      const touching = new Map<string, Edge[]>()
      for (const edge of all) {
        for (const end of [edge.source, edge.target]) {
          touching.set(end, [...(touching.get(end) ?? []), edge])
        }
      }
      let frontier = addNodes([this.query.center], false)
      for (let level = 0; level < this.query.depth; level++) {
        if (frontier.length === 0 || nodes.size >= this.query.limit * 4) break
        const reached = new Set<string>()
        for (const id of frontier) {
          for (const edge of touching.get(id) ?? []) {
            reached.add(edge.source)
            reached.add(edge.target)
          }
        }
        frontier = addNodes([...reached].filter((id) => !nodes.has(id)).sort(byCodePoint), true)
      }
      add(all.filter((edge) => nodes.has(edge.source) && nodes.has(edge.target)))
    }
    return this.result(nodes, [...found.values()], candidates)
  }

  result(
    nodes: Map<string, NonNullable<GraphNode['existence']>>,
    found: Edge[],
    candidates: Map<string, IndexEntry>,
  ): Graph {
    let edges = found.filter((edge) => nodes.has(edge.source) && nodes.has(edge.target))
    let degree = degrees(edges)
    const name = (id: string) => candidates.get(id)?.summary.name ?? ''
    let order = [...nodes.keys()].sort(
      (a, b) =>
        (degree.get(b) ?? 0) - (degree.get(a) ?? 0) ||
        byCodePoint(name(a), name(b)) ||
        byCodePoint(a, b),
    )
    const truncated = order.length > this.query.limit
    if (truncated) {
      order = order.slice(0, this.query.limit)
      const kept = new Set(order)
      edges = edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target))
      degree = degrees(edges)
    }
    return {
      nodes: order.flatMap((id) => {
        const summary = candidates.get(id)?.summary
        if (summary === undefined) return []
        return {
          id,
          kind: summary.kind,
          name: summary.name,
          dimension_id: summary.dimension_id,
          degree: degree.get(id) ?? 0,
          existence: this.asOf === null ? null : (nodes.get(id) ?? null),
        }
      }),
      edges: edges.map((edge): GraphEdge => ({
        source: edge.source,
        target: edge.target,
        kind: edge.kind,
        link_type: edge.linkType,
        label: edge.label,
        weight: edge.weight,
      })),
      truncated,
    }
  }
}

function degrees(edges: readonly Edge[]): Map<string, number> {
  const degree = new Map<string, number>()
  for (const { source, target } of edges) {
    degree.set(source, (degree.get(source) ?? 0) + 1)
    degree.set(target, (degree.get(target) ?? 0) + 1)
  }
  return degree
}

/** `GET m/graph/graph`: the whole graph, or a dimension's, or the neighborhood of `center`. */
export const graph: Handler = async (load, _route, params, [vault = '']) => {
  const query = queryOf(params)
  const [derived, data] = await Promise.all([loadIndex(load, vault), dataOf(load, vault)])
  let dimension = query.dimension
  if (query.center !== null) {
    const center = derived.index.entities[query.center]
    if (center === undefined) throw notFound(`entity ${query.center}`)
    dimension ??= center.summary.dimension_id
  }
  checkTimeline(derived, query.timeline)
  let asOf: { timeline: string; at: string } | null = null
  if (query.at !== null) {
    if (!/^\d+$/.test(query.at)) throw invalid('`at` must be a moment.')
    asOf = { timeline: cursorTimeline(derived, query.timeline, dimension), at: query.at }
  }
  return new Reader(derived, data, query, asOf).graph()
}
