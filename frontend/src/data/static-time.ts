import type { components } from '@/api'

import { NotInExport, StaticProblem, type Handler, type Load } from './static-core'
import { pick } from './static-entities'

/**
 * Time reads of a static export (#375, visibility-and-sharing.md §8): each timeline's event tree
 * and cause → effect graphs, branch diffs and notes, correspondences, and each entity's
 * worldline, personal timeline and presence, recorded by the builder (`lore/static_export/
 * time.py`) and trimmed here to what a request asks (depth, limit, page, kinds).
 */

type Schemas = components['schemas']
type Intervals<T> = [string, T][]

interface TimelineFile {
  event_tree: Record<string, Schemas['EventTreeNode'][]>
  causality: Record<string, Schemas['CausalityGraphOut']>
}

/** A read the server refused, recorded as its problem (replayed as the same problem). */
interface Refused {
  problem: { status: number; code: string; title: string; detail: string }
}

interface WorldlineFile {
  segments: Record<string, Schemas['Worldline'] | Refused>
  personal: Record<string, Schemas['PersonalTimeline'] | Refused>
  presence: Record<string, Intervals<Schemas['Presence'] | Refused> | Refused>
}

/** The recorded answer, or the recorded problem thrown. */
function replay<T extends object>(found: T | Refused | undefined, what: string): T {
  if (found === undefined) throw notFound(what)
  if ('problem' in found) {
    const { status, code, title, detail } = found.problem
    throw new StaticProblem(status, code, title, detail)
  }
  return found
}

interface IndexTimelines {
  timelines: Record<string, { dimension: string; prime: boolean; lineage: string[] }>
}

function notFound(what: string): StaticProblem {
  return new StaticProblem(404, 'not_found', 'Not found', `No ${what}.`)
}

function invalid(detail: string): StaticProblem {
  return new StaticProblem(422, 'invalid_input', 'Invalid input', detail)
}

async function loadOr404<T>(load: Load, route: string, what: string): Promise<T> {
  try {
    return (await load(route)) as T
  } catch (error) {
    if (error instanceof NotInExport) throw notFound(what)
    throw error
  }
}

function intParam(params: URLSearchParams, name: string, fallback: number): number {
  const value = params.get(name)
  return value === null ? fallback : Number(value)
}

/** Our own cursors: the position after the last item returned. */
function page<T>(items: T[], cursor: string | null, limit: number) {
  const start = cursor === null ? 0 : Number(atob(cursor))
  if (!Number.isInteger(start) || start < 0) throw invalid('The cursor is invalid.')
  const end = start + limit
  return {
    items: items.slice(start, end),
    next_cursor: end < items.length ? btoa(String(end)) : null,
  }
}

const eventTree: Handler = async (load, _route, params, [vault = '', timeline = '']) => {
  const file = await loadOr404<TimelineFile>(
    load,
    `vaults/${vault}/static/timelines/${timeline}`,
    `timeline ${timeline}`,
  )
  const parent = params.get('parent') ?? ''
  const items = file.event_tree[parent]
  if (!items) {
    // An event the tree shows without sub-events lists none; anything else is unknown.
    const shown = Object.values(file.event_tree).some((level) => level.some((e) => e.id === parent))
    if (!shown) throw notFound(`event ${parent}`)
    return { items: [], next_cursor: null }
  }
  return page(items, params.get('cursor'), intParam(params, 'limit', 100))
}

const causality: Handler = async (load, _route, params, [vault = '', timeline = '']) => {
  const file = await loadOr404<TimelineFile>(
    load,
    `vaults/${vault}/static/timelines/${timeline}`,
    `timeline ${timeline}`,
  )
  const event = params.get('event') ?? ''
  const graph = file.causality[event]
  if (!graph) throw notFound(`event ${event} on the timeline`)
  const depth = intParam(params, 'depth', 2)
  const limit = intParam(params, 'limit', 200)
  // Nodes are nearest first: the ones within `depth`, up to `limit` of them.
  const within = graph.nodes.filter((node) => node.distance <= depth)
  const nodes = within.slice(0, limit)
  const kept = new Set(nodes.map((node) => node.id))
  return {
    ...graph,
    nodes,
    edges: graph.edges.filter((edge) => kept.has(edge.source_id) && kept.has(edge.target_id)),
    // Recorded at the deepest depth and largest limit: a cut there only reaches nodes farther
    // than any shallower request, unless the recorded nodes within `depth` already fill it.
    truncated: within.length > limit || (graph.truncated && within.length === graph.nodes.length),
  }
}

const diff: Handler = async (load, route, params) => {
  const recorded = await loadOr404<Schemas['BranchDiff']>(load, route, 'timeline')
  const limit = intParam(params, 'limit', 500)
  const lists = ['created', 'overridden', 'inherited_spanning'] as const
  const trimmed = { ...recorded }
  let truncated = recorded.truncated
  for (const key of lists) {
    truncated ||= recorded[key].length > limit
    trimmed[key] = recorded[key].slice(0, limit)
  }
  return { ...trimmed, truncated }
}

const note: Handler = async (load, _route, _params, [vault = '', entity = '', timeline = '']) => {
  const index = (await load(`vaults/${vault}/static/index`)) as IndexTimelines
  if (index.timelines[timeline]?.prime) throw invalid('A prime timeline has no notes.')
  const notes = await loadOr404<Record<string, Schemas['NoteOut']>>(
    load,
    `vaults/${vault}/static/notes/${entity}`,
    `entity ${entity}`,
  )
  const found = notes[timeline]
  if (!found) throw notFound(`timeline ${timeline}`)
  return found
}

const correspondences: Handler = async (load, route, params, [vault = '']) => {
  const dimension = params.get('dimension')
  if (dimension === null) return load(route)
  const recorded = (await load(`vaults/${vault}/static/correspondences`)) as {
    by_dimension: Record<string, unknown>
  }
  return recorded.by_dimension[dimension] ?? { items: [] }
}

async function worldline(load: Load, vault: string, entity: string): Promise<WorldlineFile> {
  return loadOr404<WorldlineFile>(
    load,
    `vaults/${vault}/static/worldlines/${entity}`,
    `entity ${entity}`,
  )
}

const segments: Handler = async (load, _route, params, [vault = '', entity = '']) => {
  const file = await worldline(load, vault, entity)
  const timeline = params.get('timeline') ?? ''
  return replay(file.segments[timeline], `timeline ${timeline}`)
}

const KINDS: Record<string, readonly string[]> = {
  participations: ['participation'],
  existence: ['existence_start', 'existence_end'],
  jumps: ['jump'],
}

const personalTimeline: Handler = async (load, _route, params, [vault = '', entity = '']) => {
  const file = await worldline(load, vault, entity)
  const timeline = params.get('timeline') ?? ''
  const found = replay(file.personal[timeline], `timeline ${timeline}`)
  const include = params.getAll('include')
  if (include.length === 0) return found
  const kinds = new Set(include.flatMap((name) => KINDS[name] ?? []))
  return { ...found, items: found.items.filter((item) => kinds.has(item.kind)) }
}

const presence: Handler = async (load, _route, params, [vault = '', entity = '']) => {
  const file = await worldline(load, vault, entity)
  const dimension = params.get('dimension')
  const t = params.get('t')
  if (dimension === null || t === null) throw invalid('`dimension` and `t` are required.')
  const index = (await load(`vaults/${vault}/static/index`)) as IndexTimelines
  const timeline =
    params.get('timeline') ??
    Object.entries(index.timelines).find(
      ([, info]) => info.prime && info.dimension === dimension,
    )?.[0]
  if (timeline === undefined) throw notFound(`timeline of ${dimension}`)
  const found = replay(
    pick(replay(file.presence[timeline], `timeline ${timeline}`), t),
    `presence at ${t}`,
  )
  return { ...found, t: t as Schemas['Presence']['t'] }
}

const V = '^vaults/([^/]+)'
const W = `${V}/m/worldlines/entities/([^/]+)`

/** The time reads of a static export, by route. */
export const TIME_HANDLERS: readonly (readonly [RegExp, Handler])[] = [
  [new RegExp(`${V}/timelines/([^/]+)/event-tree$`), eventTree],
  [new RegExp(`${V}/timelines/([^/]+)/causality$`), causality],
  [new RegExp(`${V}/m/branches/timelines/([^/]+)/diff$`), diff],
  [new RegExp(`${V}/m/branches/notes/([^/]+)/([^/]+)$`), note],
  [new RegExp(`${V}/m/correspondences$`), correspondences],
  [new RegExp(`${W}/segments$`), segments],
  [new RegExp(`${W}/personal-timeline$`), personalTimeline],
  [new RegExp(`${W}/presence$`), presence],
]
