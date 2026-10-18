import { compose, parseRational, validateCorrespondence, type Step } from '@lore/chronology'

import type { components } from '@/api'

import {
  NotInExport,
  StaticProblem,
  type Handler,
  type Load,
  type ProblemError,
} from './static-core'
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
}

/** A read the server refused, recorded as its problem (replayed as the same problem). */
export interface Refused {
  problem: {
    status: number
    code: string
    title: string
    detail: string
    errors?: ProblemError[]
  }
}

interface WorldlineFile {
  segments: Record<string, Schemas['Worldline'] | Refused>
  personal: Record<string, Schemas['PersonalTimeline'] | Refused>
  presence: Record<string, Intervals<Schemas['Presence'] | Refused> | Refused>
}

/** The recorded answer, or the recorded problem thrown. */
export function replay<T extends object>(found: T | Refused | undefined, what: string): T {
  if (found === undefined) throw notFound(what)
  if ('problem' in found) {
    const { status, code, title, detail, errors } = found.problem
    throw new StaticProblem(status, code, title, detail, errors)
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
  const event = params.get('event') ?? ''
  const graph = await loadOr404<Schemas['CausalityGraphOut']>(
    load,
    `vaults/${vault}/static/causality/${timeline}/${event}`,
    `event ${event} on the timeline`,
  )
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

interface CorrespondenceFile {
  by_dimension: Record<string, unknown>
  paths: Record<string, string[]>
  durations: Record<string, string>
}

/** A stored correspondence compiled with the TS engine (`null`: unresolved or invalid). */
function compiled(row: Schemas['CorrespondenceOut']) {
  const points: (readonly [bigint, bigint])[] = []
  for (const point of row.points) {
    if (point.a_t === null || point.b_t === null) return null
    points.push([BigInt(point.a_t), BigInt(point.b_t)])
  }
  if (points.length === 0) return null
  const rate = (value: Schemas['CorrespondenceOut']['rate_before']) =>
    value === null ? null : parseRational(value.num, value.den)
  try {
    return validateCorrespondence(points, {
      extrapolation: row.extrapolation,
      rateBefore: rate(row.rate_before),
      rateAfter: rate(row.rate_after),
    })
  } catch {
    return null
  }
}

/** `correspondences/map`: along the server's path for the pair, flooring at every step. */
const mapMoment: Handler = async (load, _route, params, [vault = '']) => {
  const from = params.get('from_dimension') ?? ''
  const to = params.get('to_dimension') ?? ''
  const at = params.get('t')
  if (at === null) throw invalid('`t` is required.')
  const file = (await load(`vaults/${vault}/static/correspondences`)) as CorrespondenceFile
  const path = file.paths[`${from}>${to}`]
  const source = file.durations[from]
  if (path === undefined || source === undefined) throw notFound(`dimension ${from} or ${to}`)
  const t = BigInt(at)
  const answer = (result: bigint | null) => ({
    from_dimension: from,
    to_dimension: to,
    t: at,
    result_t: result === null ? null : String(result),
    defined: result !== null,
    path,
  })
  // Unconnected dimensions map to nothing (a dimension to itself maps to the same moment).
  if (t < 0n || t > BigInt(source) || (path.length === 0 && from !== to)) return answer(null)
  const steps: Step[] = []
  let current = from
  for (const id of path) {
    const row = (await load(
      `vaults/${vault}/m/correspondences/${id}`,
    )) as Schemas['CorrespondenceOut']
    const correspondence = compiled(row)
    const forward = row.dimension_a_id === current
    const next = forward ? row.dimension_b_id : row.dimension_a_id
    const duration = file.durations[next]
    if (correspondence === null || duration === undefined) return answer(null)
    steps.push({
      correspondence,
      direction: forward ? 'ab' : 'ba',
      targetDuration: BigInt(duration),
    })
    current = next
  }
  return answer(compose(steps, t))
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
  [new RegExp(`${V}/m/correspondences/map$`), mapMoment],
  [new RegExp(`${V}/m/correspondences$`), correspondences],
  [new RegExp(`${W}/segments$`), segments],
  [new RegExp(`${W}/personal-timeline$`), personalTimeline],
  [new RegExp(`${W}/presence$`), presence],
]
